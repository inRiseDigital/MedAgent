# platform/fhir — HAPI FHIR JPA server + MedAgent interceptors

Custom HAPI FHIR image: official starter (`hapiproject/hapi:v8.10.4`, pinned — 8.10.x
patch stream per [03 §1](../../docs/solution/03-fhir-data-platform.md)) + our
interceptor JAR + `application.yaml`.

**Governing document: [docs/solution/03-fhir-data-platform.md](../../docs/solution/03-fhir-data-platform.md).**
Read §2 (pipeline position), §5 (the three interceptors) and §5.4 (hash-chained
audit) before touching anything in `interceptors/`.

## Layout

```
fhir/
├── Dockerfile            # hapiproject/hapi:v8.10.4 + interceptor JAR (loader path /app/extra-classes)
├── application.yaml      # starter config: R4, validation-on-write, partitioning, knobs per 03 §1
├── interceptors/         # Java Maven module — the ONE audited interceptor module (03 §5)
│   ├── pom.xml           # hapi-fhir 8.10.4 provided-scope (matches the image pin), JUnit 5
│   └── src/main/java/lk/medagent/fhir/
│       ├── AuthzInterceptor.java    # 03 §5.1 — role/scope + care-relationship (02 §7)
│       ├── ConsentInterceptor.java  # 03 §5.2 — runtime Consent evaluation, Redis verdicts
│       └── AuditInterceptor.java    # 03 §5.3/§5.4 — AuditEvent per event, hash chain
└── README.md
```

## Build

```bash
cd interceptors
mvn -B package          # produces target/medagent-fhir-interceptors-<version>.jar
cd ..
docker build -t medagent/fhir .    # CI does this; no local docker required for unit tests
```

`mvn -B test` runs the unit suite. HAPI dependencies are **provided-scope**: the
starter image supplies them at runtime, so the JAR must never shade its own HAPI
copies (version skew against the pinned server). The `hapi.version` property in
`pom.xml` and the image tag in `Dockerfile` must move together — a version bump
is a named runbook event (10 §9.3), never a casual edit.

## Interceptor design — pointers into 03 §5

| Class | Pointcuts (S1) | Spec |
|---|---|---|
| `AuthzInterceptor` | `SERVER_INCOMING_REQUEST_PRE_HANDLED` (+ `STORAGE_PREACCESS/PRESHOW_RESOURCES` in S2) | 03 §5.1, 02 §3/§7 |
| `ConsentInterceptor` | `STORAGE_PRESHOW_RESOURCES`, `STORAGE_PRECOMMIT_RESOURCE_CREATED/UPDATED` (invalidation); migrates to `IConsentService` in S2/S3 | 03 §5.2 |
| `AuditInterceptor` | `STORAGE_PRECOMMIT_RESOURCE_CREATED/UPDATED/DELETED` (+ read/search + denial hooks in S2) | 03 §5.3, §5.4, 08 |

Non-negotiable invariants (asserted by integration tests from S2, 10 §3.4):

- **Fail closed.** core-api unreachable ⇒ staff clinical reads deny, never allow.
  The S1 skeleton fails closed on *everything*; reads can be let through in local
  dev only via `MEDAGENT_AUTHZ_PERMISSIVE_READ=true` (must be `false` in
  staging/pilot — CI-asserted).
- **No storage path around the interceptors.** Audit coverage is 100% (NFR-8)
  because this is the single choke point.
- **Order is load-bearing** (03 §2): authz → consent → validation → storage → audit.

## Runtime env

| Var | Purpose |
|---|---|
| `HAPI_DB_URL` / `HAPI_DB_USER` / `HAPI_DB_PASS` | Postgres datasource (`hapi_db`) |
| `MEDAGENT_AUTHZ_DECISION_URL` | core-api decision endpoint (02 §7.2) |
| `MEDAGENT_REDIS_URL` | shared authz/consent decision cache (ADR F-4) |
| `MEDAGENT_AUTHZ_PERMISSIVE_READ` | S1 dev bootstrap only — see above |

## Network posture

HAPI is **never exposed publicly** (01 §1 design rule 1): reachable only from
core-api, agent-service and the gateway's internal `/fhir` entrypoint
(`platform/gateway/dynamic/routes.yaml`). Compose/IaC enforce it; nothing in
this directory may publish a host port.
