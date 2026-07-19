# platform/gateway — Traefik edge gateway

Single entry point for the platform: TLS termination, routing, rate limiting,
security headers, structured access logs.

**Governing document: [docs/solution/01-system-architecture.md](../../docs/solution/01-system-architecture.md) §1**
(edge layer, design rules; Traefik per ADR A-2). Ops standards: 10 §1/§2.1.

## Files

```
gateway/
├── traefik.yaml          # STATIC config: entrypoints (web/websecure/internal),
│                         # file provider -> dynamic/, JSON access log w/ redaction
├── dynamic/
│   ├── routes.yaml       # route -> service map (01 §1/§2), middlewares
│   └── tls.yaml          # mkcert cert paths via env (dev); ACME supersedes in staging/pilot
└── README.md
```

The gateway image (10 §1) is Traefik + these configs; compose mounts
`dynamic/` with `watch: true` so route changes apply without restarts.

## Route map (dev host `localhost`; per-env hostnames injected by IaC)

| Route | Target | Notes |
|---|---|---|
| `/api/core/*` | `core-api:8000` | prefix stripped |
| `/api/agent/*` | `agent-service:8000` | prefix stripped; chat streaming |
| `/notify/*` | `notify-service:8000` | prefix kept (`/notify/ticket`, `/notify/stream`); ticket param never logged (02 §11) |
| `/auth/*` | `keycloak:8080` | prefix kept (`KC_HTTP_RELATIVE_PATH=/auth`); admin console NOT on this route |
| `/fhir/*` | `fhir:8080` | **internal entrypoint ONLY — see below** |
| `/` | `web:3000` | catch-all, lowest priority |

### `/fhir` is not public — ever

HAPI is **never exposed publicly** (01 §1 design rule 1; 03 §1). The `/fhir`
router is bound exclusively to the `internal` entrypoint (`:8443`), which is
never port-published on the host — it exists solely so service-to-service FHIR
calls can transit the gateway for uniform TLS and access logging. Tokens on
this path must carry the `fhir-gateway` audience (02 §2) and are re-verified by
the HAPI authz interceptor (03 §5.1). Do not "fix" a dev connectivity problem
by moving this router to `websecure`.

## Middlewares

- `security-headers` — HSTS (1 y, incl. subdomains), `nosniff`, frame-deny,
  referrer policy, no server-version disclosure.
- `rate-limit-default` (100 r/s avg, burst 200) and `rate-limit-auth`
  (20 r/s avg on `/auth`) — pilot defaults, tuned from k6 baselines (10 §8).
- `strip-api-core` / `strip-api-agent` — public prefix removal.
- Forwarded headers are trusted **only** from the internal network ranges
  declared per entrypoint in `traefik.yaml` — tighten per environment in IaC.

## AuthN at the gateway — S1 position

JWT validation is enforced **at the services** in S1: every resource server
validates issuer/audience/scope, and the HAPI authz interceptor re-verifies on
the FHIR path (defence in depth, 03 §5.1). A gateway-level JWT plugin is
evaluated later under **ADR A-2** (APISIX/plugin route); if adopted it *adds* an
outer rejection layer — service-side validation is never removed.

## TLS

Dev: mkcert certs, paths via `MKCERT_CERT_FILE` / `MKCERT_KEY_FILE`
(`dynamic/tls.yaml`, Go-template env substitution; compose mounts certs at
`/certs`). Staging/pilot: ACME automation per 10 §5 — IaC adds the resolver and
drops the static cert store.
