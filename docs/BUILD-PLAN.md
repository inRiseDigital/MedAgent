# MedAgent Platform — Build Plan (all phases)

Living execution tracker. Derived from [11-sprint-plan-phase-a.md](solution/11-sprint-plan-phase-a.md)
and the solution set, but this file tracks **actual build + test status**, not design.

**Rule of this build:** nothing is "done" until it runs in the stack, has data flowing
through it, and a test proves it. Every task carries a **verify** gate.

## Status legend
- `[x]` done and verified in the running stack
- `[~]` in progress
- `[ ]` not started
- `[B]` Phase B (deferred)

Each task: **Build** → **Verify** (insert data / call it / assert) → commit.

---

## Phase 0 · Foundations — DONE
- [x] Monorepo scaffold (apps/web, services/*, platform/*, packages/*, infra/*) · verify: tree + git
- [x] `docker compose up` data tier: postgres (3 DBs + roles), redis (per-service ACL) · verify: `\l`, ACL ping
- [x] core-api built, `alembic upgrade head` · verify: `/healthz`, `/readyz`, tables present
- [x] agent-service, notify-service up · verify: `/healthz` + `/readyz`
- [x] web (Next 16) up in Docker · verify: `/kiosk` `/portal` 200, `/queue` 307→login
- [x] Identity spine code: BFF OIDC, session store, SSE ticket, `/internal/authz/decision`
- [x] Live-queue vertical slice · verify: register→check-in→queue returns enriched rows

---

## Phase A · S1 — Platform spine (complete + verify)
- [x] **HAPI FHIR up** (stock, dev-bootstrap) — `hapiproject/hapi:v8.10.0-3` against `hapi_db`
  - verified: `hapi_db` populated (58 hfj_* tables); `GET /fhir/metadata` → 200. (Custom interceptor image is S2.)
- [x] **Keycloak up** — image built; realm-as-code applied via config-cli one-shot service
  - verified: `keycloak` DB populated (100 tables); realm `medagent` with all 11 roles + 7 clients (web, core-api, agent-service, notify-service, kiosk-device, fhir-gateway, keycloak-config-cli); OIDC discovery resolves; dev users dr_demo/reception_demo/patient_demo present
- [x] **Seed FHIR data** — Patient + Encounter + Observation via a transaction bundle (stock HAPI, dev-bootstrap)
  - verified: 201 for all three (Patient/1002, Encounter/1000, Observation/1001); search by PHN identifier → Nimal Perera; search Observation by LOINC 8867-4 → HR 78 beats/minute. (AuditEvent verification waits for the custom interceptor image in S2.)
- [x] **Real auth end-to-end** — AUTH enabled on core-api; `dr_demo` token from Keycloak
  - verified: no token → 401, bad token → 401, valid dr_demo token → 200; token `iss`=public issuer, roles include `doctor`. Split-horizon fixed: services validate `iss` against the public issuer but fetch JWKS from `KEYCLOAK_INTERNAL_URL` (new setting in all 3 services). Test token minted via a dev-only `dev-cli` direct-grant client. (Audience `aud:*` enforcement still TODO S2.)
- [x] **Gateway (Traefik)** — self-signed localhost cert (openssl), `https://localhost` live
  - verified: `/auth/realms/medagent` 200, `/` 200, `/api/core/...` 401 (auth enforced); FHIR off the public entrypoint.
- [x] **BFF login flow** — full OIDC round-trip via the gateway, verified with a cookie jar
  - verified: login → Keycloak → dr_demo credentials → callback (token exchange over internal URL) → `__Host-session` cookie → 307 to `https://localhost/queue`; `/api/auth/session` authenticated:true; `/queue` 200. Web OIDC split-horizon added (authorize/logout public, discovery+token-exchange internal); Keycloak `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true`; `web` Redis ACL user added; redirect built from forwarded headers (not the internal bind).
  - [x] FOLLOW-UP 1 (roles) FIXED — session now `roles: ["doctor"]`. Root cause: Keycloak ignores `defaultClientScopes` on the client PUT (and config-cli doesn't apply it) — scope assignments are a sub-resource (`/clients/{id}/default-client-scopes/{scopeId}`). Fixed in the dev bootstrap.
  - [x] FOLLOW-UP 2 (dev flow) FIXED — reproducible via a compose one-shot `keycloak-dev-bootstrap` (dev/keycloak-bootstrap.py, admin REST, idempotent) that sets the web default scopes and binds the dev `browser` flow after the realm import. `docker compose up` now yields a working dev login with roles.
  - NOTE: config-cli in this setup creates resources but does not apply client default-scope assignments or custom auth-flow executions — the dev bootstrap covers the gap; prod scope/flow assignment needs the same sub-resource approach (tracked for S2 hardening).
- [x] **Audit trail → FHIR AuditEvent** (app-side dispatcher, interim until the S2 interceptor) — core-api drains the audit_outbox into FHIR AuditEvents on an interval + an internal flush endpoint; every commit/check-in/registration becomes a queryable AuditEvent (NFR-8). Verified: 9 AuditEvents written, outbox drained. (Interceptor-enforced audit on *reads* + hash-chaining is S2.)
- [ ] **CI green** — lint/typecheck/unit/eval-gate run in GitHub Actions · verify: workflow passes on a PR
- [ ] **Commit lockfiles** (pnpm-lock.yaml, uv.lock per service) so builds are reproducible · verify: `--frozen-lockfile` build

## Phase A · S2 — Identity & check-in
- [ ] Face-service HMAC webhook contract fully wired (dual-key rotation, replay window) · verify: signed/unsigned/replay tests green in-stack
- [ ] `ext_face_id` enrolment linkage flow (portal deep-link stub → store id) · verify: enrol→link→check-in round-trip
- [ ] Consent gate live: revoked consent → silent drop + AuditEvent · verify: assert nothing surfaces, audit row present
- [ ] Manual fallback UI (receptionist search → confirm → enqueue) · verify: click-path creates queue entry
- [ ] Kiosk route real states (recognised / not-recognised) · verify: face-sim drives kiosk view
- [~] **Custom FHIR interceptor image — build de-risked** (2026-07-23): `platform/fhir/interceptors`
  compiles + packages against HAPI 8.10.0 (`mvn -B package` → BUILD SUCCESS, JAR emitted). Blocking
  version bug fixed (pom hapi.version 8.10.4→8.10.0). NOT yet swapped into the stack — see note below.
- [ ] **Authz interceptor calls `/internal/authz/decision`** (Java) — care-relationship enforced at FHIR boundary
  - verify: doctor with active grant reads patient → 200; without grant → 403; core-api down → deny (fail-closed)
  - NOTE: interceptors are still S1 skeletons (AuthzInterceptor fail-closed with no decision call;
    AuditInterceptor logs-only, writes-only, no persistence). Swapping the custom image in now would be
    net-negative: no real enforcement gain yet + high risk (fail-closed authz breaks the agent/portal/summary
    reads). The security functions run at the APP layer today (core-api /internal/authz/decision decision
    service, Redis consent cache, outbox→AuditEvent dispatcher — all verified). Promoting enforcement INTO
    HAPI = defense-in-depth for prod; needs real interceptor logic (HTTP→core-api from Java, JWT extract,
    compartment enforce, AuditEvent persistence + hash-chain) done test-first, on a side port, before swap.
- [ ] SSE ticket auth end-to-end (browser EventSource → notify stream) · verify: check-in event reaches doctor UI live

## Phase A · S3 — Doctor workspace & conversational agent
- [x] **Patient summary card (FR-2.2)** — doctor patient page renders the summary from core-api /patients/{phn}/summary: name/age/gender, allergy chips (red for high criticality), active problems, active medications. Verified for Nimal (diabetes/hypertension, Metformin, Penicillin) beside the chat + sign-off panels. (p95 load-test vs Synthea is an S6 gate.)
- [ ] Patient search UI (name/PHN/phone) · verify: results render, open requires grant
- [x] **Comprehensive clinical agent with citations (real Claude over FHIR)** · 15 tools covering the full record — summary, record-overview, conditions, medications, allergies, vitals, labs+diagnostic reports, immunizations, encounters, notes/documents, procedures, appointments, family history, social history, and a medication-safety screen. Verified: "full picture + is amoxicillin safe?" → pulled 13 cited resources across all domains AND returned "AVOID amoxicillin — penicillin anaphylaxis, hard stop" with beta-lactam cross-reactivity reasoning, flagged missing vitals/renal function, suggested alternatives + work-up, all [general knowledge]-marked, ending "requires your sign-off". LangGraph ReAct (claude-sonnet-5). (Orchestrator write-intent routing + ≥150-case eval gate still to build.)
- [x] **Conversational agentic interface with write-intent routing** (primary UX): multi-turn
  cited chat that also DRAFTS actions. A "prescribe/start/give X" instruction triggers
  draft_prescription → deterministic screen → a staged sign-off card (data-proposals frame),
  never a free-text commit. Verified: "prescribe amoxicillin" → staged proposal verdict BLOCK
  (ALLERGY_CLASS), agent refuses to claim it prescribed; "start paracetamol" → staged proposal
  verdict PASS. Chat UI renders proposals as inline sign-off cards (verdict badge; Sign & commit
  for pass, disabled on block, routed to the panel on warn) posting to /api/proposals/commit.
- [x] **Chat UI in the doctor workspace** · verified end-to-end via the gateway: login (dr_demo) → BFF `/api/chat` (attaches session token) → agent-service (auth enforced) → cited streamed answer; patient page renders the ChatPanel (streaming text + citation chips + quick prompts). Custom lightweight SSE reader (no ai-sdk dep). BFF proxy streams the agent's AI SDK frames through untouched.
- [ ] Conversational memory within an encounter (checkpointer) + resume · verify: close/reopen tab, thread resumes
- [ ] English STT v1 (server-relayed provider) · verify: dictation → text in note field
- [x] **AI eval gate (blocks merge on regression)** — evals/run.py runs the golden set with hard thresholds: Rx-safety graded against the deterministic engine (exact-match, 100% required), LLM classes (summary_qa/citation) run in --live mode else skipped. Verified: 14/14 rx_safety cases pass → exit 0; a planted regression (warfarin+ibuprofen mislabelled pass) → 93% → exit 1. CI (eval-gate.yml) invokes it as a required check with --output results JSON. (Growing to ≥150 cases + live citation grader is ongoing.)

## Phase A · S4 — Write-back & Rx safety
- [x] **Structured proposals commit to FHIR + audit** (core-api /api/v1/proposals/commit) — diagnosis→Condition, prescription→MedicationRequest (with rx-safety-verdict extension), vitals→Observation, note→DocumentReference. Verified: hypertension→Condition/1013, paracetamol→MedicationRequest/1014, all audited.
- [x] **Deterministic Rx-safety engine (ADR AG-2)** — curated DDI dataset + drug-class map + dose ranges in agent-service (app/rxsafety); verdict pass/warn/block computed deterministically, fail-closed (dataset down → block). Wired into the chat's screen_medication tool + a POST /api/v1/rx-safety/screen endpoint for the write-back flow. Verified 8/8 clinical cases (warfarin+NSAID→block, penicillin-allergy+amoxicillin→block, cephalexin→warn cross-reactivity, SSRI+MAOI→contraindicated, dose-exceeded→warn, safe combos→pass) AND end-to-end via chat: "can I prescribe amoxicillin?" → engine BLOCK (ALLERGY_CLASS) narrated faithfully by the LLM with alternatives + sign-off deferral.
- [x] **Safety-gated sign-off** — prescriptions RE-SCREENED at commit via the deterministic engine, server-side (not trusting the UI): verified amoxicillin→409 block (unwriteable), cephalexin→422 without override / committed with an audited override_reason→MedicationRequest/1015. Step-up (acr=loa2) gate present, enforced when step_up_enforced=true (off in dev). (Agent-initiated interrupt proposals + UI proposal card still to build.)
- [x] **Write-back proposal card + verdict banner** in the workspace — draft a prescription, "Check safety" shows the deterministic pass/warn/block banner with findings, "Sign & commit" is disabled on block and requires an override reason on warn. BFF proxy (/api/proposals/prescreen|commit) + core-api /proposals/prescreen. Verified via browser: amoxicillin→block banner + commit 409, paracetamol→pass; panel renders on the patient page.
- [ ] UAT scripts · verify: clinician walkthrough passes

## Phase A · S5 — Patient portal & notifications
- [x] **Patient portal — self record + access log** (FR-5.1/5.3/5.8). Patient↔record binding: patient_demo carries a `phn` user attribute (dev bootstrap; Keycloak 26 unmanaged-attrs enabled) mapped into the web token; the session exposes patientPhn; the portal resolves the patient from it. core-api GET /api/v1/patients/{phn}/summary serves problems/meds/allergies/vitals/appointments. Verified: patient_demo login → session patientPhn 55246820131 → /portal renders "Welcome, Nimal Perera" with diabetes/hypertension, Metformin, Penicillin allergy, and the access log.
- [x] **Visit-summary export (FR-5.6, 07 §8)** — core-api GET /patients/{phn}/summary/document?format=html|fhir. `html`: self-contained printable visit summary (facility branding, generation timestamp, requesting-identity watermark, document ID VS-…; browser Print→Save-as-PDF). `fhir`: full `$everything` bundle as an attachment (data portability, FR-6.4). Both AUDITED as an export (outbox `record_exported` → AuditEvent action E → shows in the patient access log, 07 §10). Portal exposes both via a BFF proxy route (/api/portal/export, PHN from session — patient exports only their own). Verified in-stack: HTML doc renders Nimal's problems/meds/Penicillin-crit + doc-id/watermark; FHIR export = Bundle total 21 (Patient/Conditions/Meds/Observations/Allergy/Appointment/DiagnosticReport/DocumentReference/Encounter/Immunization/Consent); access log shows two action-E `record_exported` events; web tsc clean. (Production: server-side PDF binary + registration as a DocumentReference in object storage — 03 §8.1.)
- [x] **Consent toggle wired to the face gate (FR-5.2)** — portal toggle → core-api PUT /patients/{phn}/consent updates the MPI `face_consent` flag the webhook reads, writes a versioned FHIR Consent (permit/deny), audits, and publishes a cache invalidation (immediate effect, 03 §5.2). Self-guarded (patient can only change their own via the `phn` claim; PHN comes from the session, not the client). Verified: ON → MPI `t` + Consent resource; OFF → MPI `f`.
- [x] **Personal access log (FR-5.8) from AuditEvent** — GET /api/v1/audit/access-log?patient= queries AuditEvents referencing the patient and returns a human-readable trail (who/action/type/override reason). Verified for Nimal: shows the committed prescriptions + the audited override reason. (Read-access entries arrive with the S2 audit interceptor.)
- [ ] Booking v1 · verify: create/reschedule/cancel Appointment
- [x] **notify-service send API (email/sms/push)** — POST /notify/send dispatches via the channel adapter (email→SMTP/mailpit, sms/push→logging stubs). Verified: authenticated send → 202, mailpit receives.
- [x] **Reminder scan (scheduled job)** — scans FHIR for upcoming booked appointments within a lookahead window and sends a reminder per patient, deduped via a Redis set, respecting 20:00–08:00 quiet hours; lifespan loop + POST /internal/notify/reminders/run. Verified: scan → mailpit "Appointment reminder" to Nimal; re-run deduped (sent 0). (Channel-preference/consent enforcement + Si/Ta templating are Phase B.)

## Phase A · S6 — Hardening & go-live
- [~] Security pass: secret hygiene, dep audit, authz/rate-limit review · see [SECURITY-REVIEW.md](SECURITY-REVIEW.md)
  - [x] **Secret hygiene verified** — real secrets gitignored (.gitignore:50); full git-history scan found only the sk-ant-dummy placeholder (no real leak).
  - [x] **Dependency audit — full stack clean.** Caught + fixed 5 high Next.js CVEs (App-Router middleware/proxy bypass, SSRF ×2, DoS) via next ^16.2.11 + pnpm overrides (sharp/postcss); `pnpm audit --prod` → 0. Python services (core-api/agent/notify) via `pip-audit` on installed packages → 0.
  - [x] **AuthN/Z + rate-limit + audit + PHI review** recorded (app-layer authz verified; FHIR-boundary interceptor deferred as accepted risk R-1).
  - [ ] Automate both audits as a CI merge gate (R-2); Python-service `pip-audit` in CI.
- [~] Perf vs NFRs (k6): check-in burst, chat concurrency, record load · verify: thresholds met
  - [x] **`record-load.js` built + run** (N VUs open summary + search via the real gateway path). Caught a real connection-pooling bug: core-api created a new httpx client per request → stale-keepalive `RemoteProtocolError` → intermittent 500s under load. FIXED: shared bounded FHIR pool + retry-once (app/fhir_client.py); single-flight JWKS refresh so a cold-cache burst can't stampede Keycloak into 401s (app/auth.py). Evidence run 30 VUs/15s via gateway: **0% errors, summary p95 1.72s (<2s NFR-2), search p95 ~100ms (<500ms staging target), 100% checks**. Full 3×-pilot gate runs on staging (03 §157); dev-box + Windows-host long runs add false client-side connection failures (documented in infra/perf).
  - [ ] chat-concurrency.js (first-token p95 < 2s) + soak.js — remaining k6 scenarios
- [x] **Degradation paths + runbooks + restore drill** · see [RUNBOOKS.md](RUNBOOKS.md). Restore drill VERIFIED 2026-07-23: dumped app_db + hapi_db, restored into scratch DBs, row counts matched exactly (patients_mpi 3/3, audit_outbox 15/15, hfj_resource 33/33), pg_restore exit 0, scratch cleaned. Backup/restore procedure + service-degradation responses (HAPI/core-api/notify/Keycloak/Redis/Anthropic down) + everyday checks documented. (Audit-chain hash verify pending the hash-chaining interceptor, 03 §5.4.)
- [ ] Compliance pack: DPIA-lite, threat model, consent export, audit report · verify: pack assembled
- [ ] Observability dashboards + alerts · verify: golden-signals + agent dashboards live
- [ ] Pilot training + feedback loop

---

## Phase B · National scale-up (deferred)
- [B] Lab network (LIS hub, ASTM/HL7, ServiceRequest/Specimen/DiagnosticReport) — FR-8.x
- [B] Imaging (PACS/DICOMweb, ImagingStudy, AI pre-read worklist) — FR-9.x
- [B] Closed-loop referrals (ServiceRequest+Task) — FR-10.x
- [B] National scheduling / waitlists — FR-11.x
- [B] Telemedicine (WebRTC) — FR-12.x
- [B] Child health: Immunization, growth flagging, CHDR — FR-7.3-7.7
- [B] Registries & surveillance, DHIS2 feed, notifiable disease — FR-14.x
- [B] National integrations: NDHX, HHIMS facade, SLUDI binding — §09
- [B] SNOMED CT (licence-gated), full LOINC, NMRA national register
- [B] Offline-first PWA sync (PowerSync/RxDB) — NFR-5
- [B] Si/Ta translations, TTS
- [B] Break-glass automated workflow, guardian full lifecycle, RelatedPerson projection
- [B] Elasticsearch offload, Postgres partitioning at national volume, HA/DR tightening
- [B] Voice dictation Si/Ta, K8s substrate

---

## Continuous learning & self-improvement (governed) — cross-cutting, starts S3
The system learns from use and improves itself, within clinical-safety guardrails.
**Hard rule:** the deterministic Rx-safety engine and its DDI dataset are NEVER
auto-modified — dataset changes are clinician-reviewed PRs only (04, 09). Auto-learning
optimises the LLM/agent layer and operations, always eval-gated and reversible.

- [x] **Feedback capture** — POST /api/v1/feedback captures PHI-free signals (answer ratings, proposal accepted/rejected/overridden, refusals) into a bounded Redis list; raw questions hashed server-side. Verified: 4 events captured, question stored only as a hash.
- [x] **Drift/quality metrics** — GET /api/v1/feedback/metrics: thumbs-down rate, reject/override rates, refusals. Verified live (0.5/0.5/0.5 on the test set).
- [x] **Auto candidate generation (human-reviewed)** — app/learning/analyze.py turns thumbs-down → summary_qa candidates and rejected/overridden proposals → rx_safety_review candidates in evals/candidates/ (needs_review). GOVERNANCE enforced: writes only under evals/candidates/, NEVER the rx-safety dataset or prompts; promotion is a human PR that must pass the eval gate. Verified: 3 candidates generated.
- [ ] **Auto eval-set growth** — failure patterns + rejected proposals become new golden eval cases
  automatically (queued for human confirm) · verify: a rejected answer appears as a candidate eval case
- [ ] **Drift & quality monitoring** — online sampled eval-pass-rate, refusal rate, citation coverage,
  latency/cost trended on a dashboard · verify: regression triggers an alert
- [ ] **Improvement loop** — proposed prompt/tool/routing changes run the full eval gate in CI; merged
  only if they beat the baseline; auto-rollback on regression · verify: a worse prompt is blocked
- [ ] **Shadow / A-B evaluation** — new agent versions run in shadow against live traffic before
  promotion · verify: shadow metrics compared, no user-facing change until promoted
- [ ] **Self-tuning ops** (safe, non-clinical) — rate limits, cache TTLs, summary query sets tuned
  from observed load · verify: change logged + reversible
- Governance: model/prompt/dataset versions pinned and recorded on every clinical output
  (rx-safety verdict extension, citations); human-in-the-loop sign-off is never removed.

## Cross-cutting (continuous)
- Test-as-you-go: every task inserts real data and asserts behaviour before moving on.
- Architecture improvements logged here as ADRs/notes when made.
- Commit after each verified task with a descriptive message.
- The conversational agent is the primary clinician interface; the classic UI (queue, cards,
  forms) is the deterministic fallback and the surface for structured sign-off.

## Architecture improvements log
- 2026-07-21: Redis channel/key namespaces reconciled across builders (`events:*`, `authz:*`, `face:*`, `sse:ticket:*`); ACL rewritten to strict format. (commit 2d9845f)
- 2026-07-21: SSE ticket issuance consolidated in notify-service per 02 §11 (removed from core-api). (commit 9a42891)
- 2026-07-21: web Docker build fixed to repo-root context for pnpm workspace resolution. (commit 28c14ca)
- 2026-07-21: **Keycloak realm import fixed** — compose used native `--import-realm` which cannot read config-cli YAML. Added a proper `keycloak-config` one-shot service (config-cli) and switched keycloak to plain `start-dev`. Fixed 3 realm-file bugs: a literal `$(env:...)` in a comment (config-cli substitutes over raw file text), a `break_glass` description exceeding Keycloak's varchar(255), and a `CONFIGURE_TOTP` required-action missing `providerId`.
- 2026-07-21: **Decision — stock HAPI for dev-bootstrap.** The S1 authz interceptor is a blanket fail-closed skeleton (denies every write), so the custom fhir image cannot accept seed data. Bring up stock `hapiproject/hapi:v8.10.4` against `hapi_db` for dev/testing now; swap to the custom interceptor image in S2 when the interceptors carry real decision logic.
- 2026-07-21: National architecture chart reviewed — confirms the six-layer design; noted Provider registry and Facility registry as explicit national core registries (map to FHIR Practitioner/PractitionerRole + Organization/Location).
- 2026-07-21: **Fixed invented HAPI image tag** — `hapiproject/hapi:v8.10.4` does not exist on Docker Hub; corrected the fhir Dockerfile and dev override to the real latest 8.10.x tag `v8.10.0-3`. (The pom `hapi.version=8.10.4` for the interceptor build should be re-checked against real Maven artifact versions in S2.)
- 2026-07-21: **HAPI FHIR live + clinical data flowing** — stock HAPI on `hapi_db`; inserted Patient/Encounter/Observation via transaction bundle and verified read-back + LOINC search. dev override: `infra/compose/docker-compose.dev-fhir.yml`.
- 2026-07-21: **Keycloak issuer split-horizon fixed** — all 3 services now validate token `iss` against the public issuer (`keycloak_issuer`) but fetch JWKS directly from the internal certs endpoint (`keycloak_internal_url`, new setting), instead of following discovery's public `jwks_uri`. Real-auth verified (401/401/200). Follow-up: `dev-cli` direct-grant client was created via admin REST for testing — make it a reproducible dev bootstrap artifact (config-cli would delete sibling clients if added to a managed file, so needs care).
