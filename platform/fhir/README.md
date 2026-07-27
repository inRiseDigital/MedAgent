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

## AuthzInterceptor modes (backlog 0.1)

`MEDAGENT_AUTHZ_MODE` selects behaviour:

- **`skeleton`** (default) — S1 fail-closed contract (writes always denied; reads
  denied unless `MEDAGENT_AUTHZ_PERMISSIVE_READ=true`). This is what the tests and
  the current dev stack assume; the running compose does not register the
  interceptor at all, so the boundary is inert today.
- **`enforce`** — the implemented boundary controls (unit-tested, 14 cases):
  1. **Trusted-service credential** — every request must carry
     `X-MedAgent-Service-Key` matching `MEDAGENT_SERVICE_KEY` (constant-time compare).
  2. **Role/scope gate** — only `doctor|nurse|admin|system` (from `X-MedAgent-Roles`)
     may write clinical types; receptionists cannot.
  3. **No-trawl** — a search of a patient-**compartment** type (Observation,
     Condition, MedicationRequest, DiagnosticReport, DocumentReference,
     AllergyIntolerance, Immunization, Encounter, Specimen, ImagingStudy, Procedure)
     without a `patient`/`subject`/`_id` param is rejected. **Workflow** types
     (Task, ServiceRequest, Flag, Appointment) are exempt so facility-scoped `_tag`
     worklists (referral inbox, surveillance line-lists) still work.
  4. **purposeOfUse** stamped (TREAT default / BTG / PATRQT from `X-MedAgent-Purpose`).
  Any evaluation error fails closed.

### Activating enforce mode (staged — R-1, do NOT flip blindly)

1. Register the interceptor: restore the interceptor-registering `application.yaml`
   (the dev compose currently overrides `SPRING_CONFIG_LOCATION` to work around a
   base-config/search-routing issue — 03 §1 runbook) so HAPI actually loads it.
2. Set on the `fhir` service: `MEDAGENT_AUTHZ_MODE=enforce`,
   `MEDAGENT_SERVICE_KEY=<secret>`.
3. Have core-api/agent-service forward `X-MedAgent-Service-Key` (the same secret)
   and `X-MedAgent-Roles: system` on every FHIR call (FHIRClient change; inert
   until the interceptor is in enforce mode).
4. Validate on a **side port / staging** first: confirm the platform's own writes,
   patient-scoped reads, and `_tag` worklist searches all pass, and that a
   credential-less request is denied — before any pilot rollout.

**Still S2 (not yet implemented):** per-user care-relationship enforcement via the
Redis decision cache + core-api `GET /internal/authz/decision`. Enforce mode today
is the service-trust + role + no-trawl boundary; the per-user compartment decision
call is the next step (the corresponding JUnit case stays `@Disabled` and honest).

## Runtime env

| Var | Purpose |
|---|---|
| `HAPI_DB_URL` / `HAPI_DB_USER` / `HAPI_DB_PASS` | Postgres datasource (`hapi_db`) |
| `MEDAGENT_AUTHZ_MODE` | `skeleton` (default) or `enforce` (see above) |
| `MEDAGENT_SERVICE_KEY` | shared trusted-service credential for `enforce` mode |
| `MEDAGENT_AUTHZ_DECISION_URL` | core-api decision endpoint (02 §7.2) — S2 |
| `MEDAGENT_REDIS_URL` | shared authz/consent decision cache (ADR F-4) — S2 |
| `MEDAGENT_AUTHZ_PERMISSIVE_READ` | S1/skeleton dev bootstrap only — see above |

## Network posture

HAPI is **never exposed publicly** (01 §1 design rule 1): reachable only from
core-api, agent-service and the gateway's internal `/fhir` entrypoint
(`platform/gateway/dynamic/routes.yaml`). Compose/IaC enforce it; nothing in
this directory may publish a host port.
