# Security review — as-built (S6)

Operational record of the S6 security pass: what was **verified**, what was
**fixed**, and the **accepted-risk register**. This complements the design-time
controls in [solution/08-security-privacy-compliance.md](solution/08-security-privacy-compliance.md)
— that doc states the intended posture; this one records the state of the
running system and is updated each pass.

Last pass: **2026-07-23**. Reviewer: build team. Scope: local compose stack at
the current commit; staging-only items are flagged.

## 1. Secret management — VERIFIED

- Real secrets (Anthropic API key in `infra/compose/env/agent-service.env`,
  service DB/Redis passwords, HMAC secrets) live only in gitignored env files.
  `.gitignore:50` (`infra/compose/env/*.env`) covers them; `*.env.example`
  templates with placeholders are the only committed variants.
- Full git-history scan for secret patterns (`sk-ant-…`, private-key headers,
  literal passwords) found **only** the `sk-ant-dummy-not-a-real-key`
  placeholder. No real secret has ever been committed.
- Only `infra/secrets/.sops.yaml` (the SOPS *encryption rule* file, not a
  secret) is tracked under `infra/secrets/`.
- Staging/pilot: secrets are SOPS-encrypted and CI-decrypted (10 §5); the dev
  throwaway accounts (`platform/keycloak/realm/dev-users.yaml`) are never
  applied beyond local.

## 2. Dependency audit — FIXED this pass

- `pnpm audit --prod` flagged **5 high + 6 moderate** in `next@16.2.10`:
  App-Router middleware/proxy bypass, SSRF in Server Actions and in rewrites,
  and a Server-Components DoS. The middleware bypass is directly relevant —
  route protection runs in middleware.
- Fix: pinned `next` to `^16.2.11`; `pnpm.overrides` force the two remaining
  transitive vulns in next's own tree — `sharp >=0.35.0` (libvips CVEs),
  `postcss >=8.5.10`. Rebuilt the web image. **Result: `pnpm audit --prod` →
  No known vulnerabilities found.**
- **Python services audited** (`pip-audit` against the actual installed
  packages captured from each running container — 44 core-api / 64
  agent-service / 39 notify-service): **all three → No known vulnerabilities
  found.**
- TODO: wire both audits into CI as a gate (no HIGH/CRITICAL merges). The audit
  itself is clean today; only the automation is outstanding (R-2).

## 3. AuthN / AuthZ — VERIFIED (app layer), one control DEFERRED

- **Authentication:** Keycloak OIDC, BFF confidential client + PKCE; the browser
  never sees tokens (encrypted Redis session). JWTs verified for issuer,
  signature (JWKS), expiry. Split-horizon issuer handled (public `iss`, internal
  JWKS fetch). JWKS refresh is now single-flight (S6 perf fix) so a burst can't
  stampede Keycloak into transient 401s.
- **Authorisation:** care-relationship decision service (`/internal/authz/
  decision`) + Redis consent cache; patient portal is self-scoped — the PHN
  comes from the session claim, never the client, so a patient can only ever
  reach their own compartment (verified on summary, access-log, consent,
  export).
- **DEFERRED (accepted risk R-1):** enforcement at the FHIR storage boundary
  (HAPI authz/consent/audit interceptors) is not yet live — the JAR builds but
  the interceptors are S1 skeletons (fail-closed authz would break reads). The
  equivalent controls run at the app layer today. See the risk register.

## 4. Transport, rate limiting, audit — VERIFIED

- **Transport:** all external traffic terminates TLS at the Traefik gateway;
  HAPI FHIR has **no published port** (reachable only in-network from core-api /
  agent-service). Dev uses a self-signed cert; staging uses real certs.
- **Rate limiting:** gateway `rate-limit-default` = 100 req/s (burst 200) per
  source; `/auth` tightened to 20 req/s (burst 40). Confirmed active.
- **Audit trail:** write paths record an `audit_outbox` row in the same
  transaction, dispatched to FHIR `AuditEvent` (actions C/R/U/D/E); the patient
  access log (FR-5.8) and record exports (FR-5.6, action E) surface from it.
  Read-access audit at the storage boundary arrives with the interceptor (R-1).

## 5. PHI / data protection — VERIFIED

- Audit outbox payloads and application logs carry **opaque IDs only** — no
  name/NIC/phone (spot-checked in patients/queue/consent/export paths).
- Cross-border transfer (Anthropic API, USA): clinical prompt content is
  minimised; posture recorded in 08 ADR SEC-3. No change this pass.

## 6. Accepted-risk register

| ID | Risk | Exposure | Disposition |
|----|------|----------|-------------|
| R-1 | FHIR-boundary enforcement (authz/consent/read-audit interceptors) not live | A compromised or buggy service with a valid token could over-read at HAPI; app layer still gates the real call paths | **Accepted for pilot** — app-layer controls verified; interceptor is test-first S2 work (JAR builds). Prioritise before multi-facility. |
| R-2 | Dependency audit not automated in CI | A future dep bump could introduce a CVE unnoticed | **Mostly closed** — full stack audited clean this pass (pnpm + pip-audit, 0 vulns). Remaining: add the audits as a CI merge gate. |
| R-3 | Chat-concurrency + soak load scenarios not run | LLM-path behaviour under sustained concurrency unquantified | **Open** — needs a recorded-LLM harness (avoids token burn + nondeterminism) before the gate is meaningful. |
| R-4 | Dev self-signed TLS + dev throwaway Keycloak accounts | None in prod (dev-only, path-excluded from staging apply) | **Accepted** — documented, not applied beyond local. |

## 7. Next actions

1. Add the pnpm + pip-audit runs as a CI merge gate (closes R-2; the audits
   themselves pass clean today).
2. Interceptor enforcement, test-first on a side port before swap (closes R-1).
3. Recorded-LLM harness → chat-concurrency + soak k6 (closes R-3).
4. Restore drill (both DBs to scratch, audit chain verifies) + runbooks.
