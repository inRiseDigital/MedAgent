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
- [~] **HAPI FHIR up** — build image (starter + interceptor JAR), pull base, healthy
  - verify: container healthy; `hapi_db` populated (hfj_* tables); `GET /fhir/metadata` returns CapabilityStatement
- [x] **Keycloak up** — image built; realm-as-code applied via config-cli one-shot service
  - verified: `keycloak` DB populated (100 tables); realm `medagent` with all 11 roles + 7 clients (web, core-api, agent-service, notify-service, kiosk-device, fhir-gateway, keycloak-config-cli); OIDC discovery resolves; dev users dr_demo/reception_demo/patient_demo present
- [ ] **Seed FHIR data** — insert a Patient + Encounter + Observation via FHIR transaction (through the interceptor path)
  - verify: read back by id; search by PHN identifier; confirm AuditEvent written
- [ ] **Real auth end-to-end** — turn AUTH_DISABLED off; obtain a token for `dr_demo` from Keycloak; call core-api + FHIR
  - verify: valid token → 200; missing/expired token → 401; wrong audience → 401
- [ ] **BFF login flow** — web `/api/auth/login` → Keycloak → callback → session cookie → `/queue` renders
  - verify: browser (or curl cookie jar) completes the OIDC round-trip; `/queue` shows live data
- [ ] **Gateway (Traefik)** — generate mkcert certs, bring up, route `https://localhost`
  - verify: `https://localhost/queue`, `/api/core/...`, `/auth/...` route correctly; FHIR NOT reachable publicly
- [ ] **Audit interceptor writes AuditEvent** on every read/write · verify: read a Patient → AuditEvent row appears
- [ ] **CI green** — lint/typecheck/unit/eval-gate run in GitHub Actions · verify: workflow passes on a PR
- [ ] **Commit lockfiles** (pnpm-lock.yaml, uv.lock per service) so builds are reproducible · verify: `--frozen-lockfile` build

## Phase A · S2 — Identity & check-in
- [ ] Face-service HMAC webhook contract fully wired (dual-key rotation, replay window) · verify: signed/unsigned/replay tests green in-stack
- [ ] `ext_face_id` enrolment linkage flow (portal deep-link stub → store id) · verify: enrol→link→check-in round-trip
- [ ] Consent gate live: revoked consent → silent drop + AuditEvent · verify: assert nothing surfaces, audit row present
- [ ] Manual fallback UI (receptionist search → confirm → enqueue) · verify: click-path creates queue entry
- [ ] Kiosk route real states (recognised / not-recognised) · verify: face-sim drives kiosk view
- [ ] **Authz interceptor calls `/internal/authz/decision`** (Java) — care-relationship enforced at FHIR boundary
  - verify: doctor with active grant reads patient → 200; without grant → 403; core-api down → deny (fail-closed)
- [ ] SSE ticket auth end-to-end (browser EventSource → notify stream) · verify: check-in event reaches doctor UI live

## Phase A · S3 — Doctor workspace & conversational agent
- [ ] Patient summary card (FR-2.2) from FHIR query set · verify: p95 < 2s on Synthea data
- [ ] Patient search UI (name/PHN/phone) · verify: results render, open requires grant
- [ ] Orchestrator v1 + summary agent with citations (real LLM) · verify: eval golden set ≥150 cases, citation faithfulness ≥98%
- [ ] **Conversational agentic interface** (primary UX): multi-turn chat over the patient
  record, context-aware (clinician/patient/encounter/consent stamped), streaming, with
  visible tool-calls and citation chips linking to source FHIR resources. Natural-language
  intents route through the orchestrator to specialist agents; write intents surface as
  structured proposals (never free-text commits).
  · verify: ask "what are the active meds?" → cited answer; "prescribe X" → safety-screened proposal card
- [ ] Chat UI (Vercel AI SDK) streaming against agent-service · verify: token stream renders, citation chips resolve
- [ ] Conversational memory within an encounter (checkpointer) + resume · verify: close/reopen tab, thread resumes
- [ ] English STT v1 (server-relayed provider) · verify: dictation → text in note field
- [ ] AI eval harness in CI (blocks merge on regression) · verify: intentional regression fails the gate

## Phase A · S4 — Write-back & Rx safety
- [ ] Structured proposals (Diagnosis ICD-10, Note, Vitals, Prescription) · verify: each commits a valid FHIR resource
- [ ] Rx-safety engine: load DDI dataset, RxCUI normalisation, allergy-class, dose checks · verify: warfarin+NSAID → block; dataset down → block all Rx
- [ ] Interrupt-based e-sign-off + step-up auth (loa2) for prescriptions · verify: sign→commit; step-up enforced
- [ ] Write-back proposal card + verdict banner (pass/warn/block) · verify: UI reflects engine verdict
- [ ] UAT scripts · verify: clinician walkthrough passes

## Phase A · S5 — Patient portal & notifications
- [ ] Portal: records, appointments, prescriptions, visit summaries · verify: patient sees own data only (compartment)
- [ ] Consent toggle wired to face flow · verify: flip → immediate effect (cache invalidation)
- [ ] Personal access log (FR-5.8) from AuditEvent · verify: shows reads incl. break-glass
- [ ] Booking v1 · verify: create/reschedule/cancel Appointment
- [ ] notify-service SMS + push + visit-summary auto-send · verify: mailpit/SMS-sim receives; quiet hours respected
- [ ] Reminder agent v1 (scheduled job) · verify: due-item scan fires on schedule, channel prefs honoured

## Phase A · S6 — Hardening & go-live
- [ ] Security pass: OWASP, dep audit, RBAC review, rate limits · verify: gitleaks/Trivy clean, RBAC matrix tested
- [ ] Perf vs NFRs (k6): check-in burst, chat concurrency, record load · verify: thresholds met
- [ ] Degradation paths + runbooks + restore drill · verify: restore both DBs to scratch, audit chain verifies
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

- [ ] **Feedback capture** — log every agent turn, clinician proposal edit/accept/reject, thumbs
  signal, citation click, refusal · verify: signals land in an analytics store (no PHI in features)
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
