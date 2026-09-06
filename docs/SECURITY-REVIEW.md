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
- **R-1 now largely closed:** enforcement at the FHIR storage boundary is
  **implemented, verified live, and one overlay away**. All three interceptors are
  real — Authz (ENFORCE, fail-closed), Consent (EVALUATE, deny-consent masking),
  Audit (PERSIST, hash-chained + restart-continued) — activated by the opt-in
  `infra/compose/docker-compose.fhir-enforce.yml`. Proven under ENFORCE: authorised
  read 200 + cited, gated write 201, credential-less raw read 403. The base dev
  compose still runs without it (app-layer controls gate the real paths); run under
  the overlay before multi-facility. See the risk register.

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
| R-1 | FHIR-boundary enforcement (authz/consent/read-audit interceptors) not live | A compromised or buggy service with a valid token could over-read at HAPI; app layer still gates the real call paths | **Largely closed** — all 3 interceptors real + verified live under the `docker-compose.fhir-enforce.yml` overlay (authz ENFORCE, consent EVALUATE, audit PERSIST hash-chained; read 200/write 201/credential-less 403). Residual is operational: base dev runs without the overlay, and the per-user care-relationship boundary call is the S2 follow-on. Run under the overlay before multi-facility. |
| R-2 | Dependency audit not automated in CI | A future dep bump could introduce a CVE unnoticed | **CLOSED 2026-07-23** — full stack audited clean (pnpm + pip-audit, 0 vulns) and both are now gating CI steps (`pnpm audit --prod --audit-level high`; `pip-audit --strict`), with pnpm-lock.yaml committed for reproducible installs. |
| R-3 | Chat-concurrency + soak load scenarios not run | LLM-path behaviour under sustained concurrency unquantified | **Harness built** — `infra/perf/chat-concurrency.js` (TTFB<2s gate + real-answer/no-leak checks) and `infra/perf/soak.js` (constant-arrival drift/leak gate) now exist; `AGENT_LLM_MODE=stub` runs them quota-free. Remaining: record staging-scale numbers against the production model. |
| R-4 | Dev self-signed TLS + dev throwaway Keycloak accounts | None in prod (dev-only, path-excluded from staging apply) | **Accepted** — documented, not applied beyond local. |

## 7. Next actions

1. ~~Add the pnpm + pip-audit runs as a CI merge gate~~ **Done 2026-07-23**
   (R-2 closed).
2. ~~Interceptor enforcement, test-first before swap~~ **Done** — all 3 interceptors
   real + verified live via the `fhir-enforce` overlay (R-1 largely closed; remaining:
   run under the overlay by default + the per-user care-relationship boundary call).
3. ~~Build chat-concurrency + soak k6 scenarios~~ **Done** — harness exists (R-3
   narrowed to recording staging-scale numbers against the production model).
4. Engage an accredited external assessor for the formal security certification, and
   run the clinical-validation protocol with clinicians (both externally gated).
4. Restore drill (both DBs to scratch, audit chain verifies) + runbooks.
