# Threat model (S6)

STRIDE-lite against the as-built architecture. Each threat maps to a mitigation
that is **built** (verified), **partial**, or **deferred** (with the risk ID
from [SECURITY-REVIEW.md](SECURITY-REVIEW.md)). Companion to the design controls
in [solution/08-security-privacy-compliance.md](solution/08-security-privacy-compliance.md).

Scope: the clinical platform (doctor workspace, patient portal, agent, FHIR
store, identity). Out of scope: the external face-recognition service (its own
threat model, 05 §7) and physical/host security.

## Trust boundaries

```
[Browser]──TLS──►[Traefik gateway]──►┌ web (BFF, holds tokens server-side)
                  rate-limit,         ├ core-api ─┐
                  TLS terminate       ├ agent-service ─┼──►[HAPI FHIR]──►[hapi_db]
                                      └ notify-service  │        ▲
[Keycloak]◄──OIDC/JWKS───────────────────────────┘        │
[Face service]──HMAC webhook──►[gateway /integrations/face]┘
                                          [Redis: sessions, consent cache, SSE tickets]
                                          [app_db: MPI, audit outbox, queue]
```

Boundaries crossed: Internet→gateway; gateway→services; services→HAPI;
services→Keycloak; browser session↔Redis; external face service→gateway;
services→Anthropic API (cross-border, PHI-minimised).

## STRIDE

### S — Spoofing
| Threat | Mitigation | State |
|--------|-----------|-------|
| Forged user identity | Keycloak OIDC; JWT verified for signature (JWKS), issuer, expiry; BFF confidential client + PKCE | **Built** |
| Stolen token replayed from browser | Tokens never reach the browser — held server-side in an encrypted Redis session; cookie is the only browser artifact | **Built** |
| Forged face-service webhook | HMAC-signed webhook with key-ID + timestamp/replay window (05 §3) | **Built** (dual-key rotation is S2) |
| SSE stream hijack | Single-use opaque Redis ticket (`GETDEL`), 30 s validity, not a JWT | **Built** |

### T — Tampering
| Threat | Mitigation | State |
|--------|-----------|-------|
| Client tampers with request to read another patient | Portal PHN comes from the **session claim, never the client**; care-relationship decision service gates clinician reads | **Built** (app layer); FHIR-boundary enforcement **deferred — R-1** |
| Prescription written bypassing safety | Deterministic Rx-safety engine computes the verdict server-side; the LLM only narrates; block is a hard stop; commit is safety-gated | **Built** |
| Audit record altered/deleted to hide access | Audit written via transactional outbox → FHIR AuditEvent, now **hash-chained** (SHA-256 prevHash|content) with `/internal/audit/verify` | **Built** — altering any event breaks the chain and is detected |
| Man-in-the-middle | TLS at the gateway; HAPI has no published port | **Built** |

### R — Repudiation
| Threat | Mitigation | State |
|--------|-----------|-------|
| User denies an action (view/prescribe/export) | Every write + export recorded as an AuditEvent (actor, action C/R/U/D/E, target); surfaced in the patient access log | **Built** for writes/exports; **read-access audit deferred — R-1** |
| Override of a safety warning unattributed | Override reason captured and written to the AuditEvent `outcomeDesc` | **Built** |

### I — Information disclosure
| Threat | Mitigation | State |
|--------|-----------|-------|
| PHI leaked in logs/audit payloads | Outbox payloads + app logs carry **opaque IDs only** — no name/NIC/phone (spot-checked) | **Built** |
| Over-broad record access by a valid but unauthorised clinician | Care-relationship grant required; patient-self compartment enforced | **Built** (app layer); boundary enforcement **deferred — R-1** |
| Secrets leaked via repo | Secrets gitignored; git history clean (only dummy placeholder); SOPS + CI-decrypt on staging | **Built/verified** |
| PHI exposure via cross-border LLM call | Prompt content PHI-minimised; enterprise no-training terms; posture in ADR SEC-3 | **Built** (policy); regional-hosting review is Phase B |
| Dependency CVE enabling disclosure (e.g. Next.js SSRF) | `pnpm audit` + `pip-audit` gating in CI; 5 high Next.js CVEs patched | **Built/verified — R-2 closed** |

### D — Denial of service
| Threat | Mitigation | State |
|--------|-----------|-------|
| Request flood | Gateway rate limits (100 req/s default, 20 req/s on `/auth`) | **Built** |
| Connection-pool exhaustion cascading to 500s | Shared bounded FHIR pool + retry (S6 fix); load-tested to NFR-2 at 3× pilot | **Built/verified** |
| JWKS-refresh stampede on cold cache → auth outage | Single-flight lock on the JWKS refresh (S6 fix) | **Built/verified** |
| Dependency down (HAPI/Redis/Keycloak/Anthropic) | Documented degradation paths; Rx-safety works without the LLM; queue-poll fallback when notify is down | **Built** (see RUNBOOKS.md §5) |

### E — Elevation of privilege
| Threat | Mitigation | State |
|--------|-----------|-------|
| Patient role reaching staff endpoints | Realm roles + per-endpoint role checks (`require_roles`); portal is self-scoped | **Built** |
| App-Router middleware bypass reaching protected routes | Next.js middleware-bypass CVE patched (16.2.11) | **Built/verified** |
| Compromised service over-reads at HAPI with a valid token | App-layer authz gates the real call paths | **Partial** — defence-in-depth at the FHIR boundary **deferred — R-1** |
| Break-glass / emergency access abused | Break-glass is a manual, audited procedure in Phase A (07 §8 override); automated workflow is Phase B | **Partial by design** |

## Top residual risks (ranked)

1. **R-1 — FHIR-boundary enforcement implemented AND activatable; default-off in dev.**
   All three interceptors are now **real and verified live**: `AuthzInterceptor`
   (ENFORCE — trusted-service credential + role/scope write-gate + no-trawl search
   shaping on patient-compartment types + purposeOfUse stamp, fail-closed),
   `ConsentInterceptor` (EVALUATE — masks a resource whose subject has an active
   record-sharing deny-consent), `AuditInterceptor` (PERSIST — complete AuditEvent,
   hash-chained, now **continued across restarts**). Header forwarding from both
   services is wired (`X-MedAgent-Service-Key/-Roles/-Purpose`). Activation is the
   opt-in overlay `infra/compose/docker-compose.fhir-enforce.yml` (registers the 3
   interceptors via env, not the full application.yaml which regresses search). Proven
   under ENFORCE: authorised read 200 + cited, gated write 201, **credential-less raw
   read 403**. Residual is now **operational, not architectural**: the base dev compose
   runs without the overlay (app-layer controls gate the real paths), and the per-user
   care-relationship decision-service call at the boundary is the remaining S2 follow-on.
   **Run under the fhir-enforce overlay by default before multi-facility rollout.**
2. **R-3 — LLM path load-tested harness now exists; staging run pending.** The two
   missing k6 scenarios are built — `infra/perf/chat-concurrency.js` (concurrent
   `/chat`: TTFB<2s server-responsiveness gate, asserts a real answer streamed + no
   tool-call leak) and `infra/perf/soak.js` (constant-arrival drift/leak gate). With
   `AGENT_LLM_MODE=stub` they run quota-free. Remaining: execute them at staging scale
   against the production model and record the numbers (the dev box + Windows host add
   false client-side connection failures — see `record-load.js`).

~~Audit tamper-evidence~~ — **resolved**: the audit trail is hash-chained
(`/internal/audit/verify`) and the chain is now **continued across process restarts**
(a restart no longer begins a fresh genesis chain).

Both remaining risks are now materially reduced — R-1's enforcement is built, verified,
and one overlay away; R-3's harness exists. Neither blocks a single-facility supervised
pilot; R-1 should run under the enforce overlay before the system holds records across
facilities, and R-3's staging numbers recorded before a public-scale gate.
