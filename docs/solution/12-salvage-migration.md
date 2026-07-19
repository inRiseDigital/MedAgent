# 12 · Salvage & Migration from Prototypes

Version 1.0 · July 2026 · MedAgent Platform
Status: Draft for review

## Executive summary

Two prototype repositories — `MedicalBot_FE` (Next.js 14) and `medical_bot_backend` (FastAPI + SQLAlchemy + LangGraph) — are frozen as reference (locked decision D1, 00-master-plan.md). This document is the precise engineering disposition: what is **ported** (with source paths), what is **rebuilt**, what is **dropped**; the data decision for the prototype's Neon-hosted database (no migration — fresh Synthea plus real enrolment at pilot, with a disposition checklist); the **week-0 security actions** with exact steps for the live credentials currently exposed in plaintext; a traceability table mapping each prototype security finding to the platform mechanism that fixes it; and the coordination items the external face-recognition service team must action. Nothing in the prototypes is load-bearing for the new platform; everything taken is taken deliberately.

## 1. Inventory — PORT

Ports are **pattern and asset transplants into new code**, not file copies: every ported item is re-implemented against the new stack (Next.js 16 + AI SDK, LangGraph 1.x, FHIR) and lands with tests.

| # | Asset | Source (prototype path) | Destination | Port notes | Sprint |
|---|---|---|---|---|---|
| P-1 | Doctor chat UX patterns: streaming chat layout, quick-prompt chips, patient overview cards, message grouping | `d:\Git\MedicalBot_FE\components\PatientChat.tsx` (859-line god component) | `apps/web` chat components + `packages/ui` (06-doctor-workspace-frontend.md) | Decompose into small components on AI SDK `useChat`; the UX flows are the salvage, the component is not — no code copy of the monolith | S3 |
| P-2 | Agent system prompt (clinical assistant behaviour, tone, guardrail phrasing) | `d:\Git\medical_bot_backend\app\agent\builder.py` | `services/agent-service/prompts/summary.v0.md` (versioned, semver header per 04-ai-agent-platform.md §4) | v0 seed for the summary agent; immediately subject to the eval gate; citations + refusal behaviours added on top | S3 |
| P-3 | Per-patient tool scoping (every tool closes over the authenticated patient context; agent cannot query another patient) | `d:\Git\medical_bot_backend\app\agent\builder.py` + `app\agent\tools.py` | agent-service FHIR read tools (agents/02-summary.md) | Pattern preserved; scope now also enforced *below* the agent by FHIR interceptors (03), so the tool scoping becomes defence-in-depth rather than the only barrier | S3 |
| P-4 | Per-tool DB session pattern (fresh session per tool invocation; no long-lived session across an agent run) | `d:\Git\medical_bot_backend\app\agent\tools.py` | agent-service tool implementations (httpx-per-call to FHIR/core-api; same isolation principle) | Translates from SQLAlchemy sessions to scoped, per-call FHIR client contexts with the clinician's token | S3 |
| P-5 | FaceRec check-in UX: toast on recognition, in-chat event card (confidence band, match status, demographics), SSE-driven | `d:\Git\MedicalBot_FE\components\PatientChat.tsx` and `d:\Git\MedicalBot_FE\app\dashboard\patients\page.tsx` (FaceRecCard/FaceRecToast inline components) | workspace event components (05-face-recognition-integration.md §5, 06) | UX kept; transport rebuilt (notify-service SSE with ticket auth + real connection state — the prototype's "Listening…" indicator was decorative) | S2 |
| P-6 | Tailwind palette / visual language | `d:\Git\MedicalBot_FE\tailwind.config.ts`, `d:\Git\MedicalBot_FE\app\globals.css` | design tokens in `packages/ui` (06) | Input to the token set only; hand-written `.dark !important` overrides are dropped (D-4 below) — dark mode is token-native in the new design system | S1 |
| P-7 | SQLAlchemy model/enum design knowledge (clinical entities: patient, diagnosis, prescription, allergy, vitals, lab order; enum vocabularies) | `d:\Git\medical_bot_backend\models\*.py` (`patient.py`, `diagnosis.py`, `prescription.py`, `allergy.py`, `lab_order.py`, `clinical_note.py`, …) | FHIR resource mapping reference (03-fhir-data-platform.md) | Reference only — nothing becomes schema; the enums inform ValueSet choices and the field inventories validate FHIR profile coverage | S1–S4 |
| P-8 | Login lockout logic pattern | `d:\Git\medical_bot_backend\app\services\auth_service.py` | superseded by Keycloak brute-force protection (02-identity-access-mpi.md) | Listed for completeness: the *requirement* survives, the implementation is Keycloak configuration, not ported code | S1 |

## 2. Inventory — REBUILD

Rebuilt from scratch against this document set; the prototype versions are unsafe or architecturally wrong, and are used at most as a checklist of endpoints/behaviours to cover.

| # | Capability | Prototype location (reference only) | Rebuilt as | Governing doc |
|---|---|---|---|---|
| R-1 | Authentication & sessions (JWT hand-rolled, localStorage tokens, placeholder signing key, open self-registration) | `app\core\security.py`, `app\routers\auth.py`, `app\dependencies\auth.py` (BE); `app\login\page.tsx`, `app\signup\page.tsx` (FE) | Keycloak 26.x OIDC (Authorization Code + PKCE), realm-as-code, admin-provisioned staff accounts, MFA/step-up | 02 |
| R-2 | All CRUD routers (patients, health records, doctors, calendar, patient portal) | `app\routers\patients.py`, `health_records.py`, `doctors.py`, `calendar.py`, `patient_portal.py` | FHIR resources via HAPI behind interceptors; non-FHIR operational state via core-api | 03, 01 |
| R-3 | SSE fan-out (in-memory `asyncio.Queue` per process — breaks beyond one worker; unauthenticated event injection) | `app\routers\agent.py` | notify-service: Redis pub/sub → stateless SSE with ticketed auth | 01 §1, 05 |
| R-4 | Schema management (runtime `create_all` + vestigial Alembic, dual mechanism) | `app\database.py`, `migrations\` | Alembic-only for `app_db`; HAPI owns `hapi_db`; CI guards | 10 §9 |
| R-5 | Chat streaming (completion-then-word-split fake streaming) | `app\routers\agent.py` (BE), `components\PatientChat.tsx` (FE) | LangGraph `astream_events` → AI SDK data protocol, real token streaming | 04 §2.4 |
| R-6 | Face webhook (`POST /api/v1/agent/face-recognized`, unauthenticated) | `app\routers\agent.py` | HMAC-signed, timestamped, idempotent webhook behind the gateway | 05 §3 |
| R-7 | Audit logging (partial `audit_log` table, app-level, bypassable) | `models\audit_log.py` | FHIR AuditEvent emitted by interceptor — cannot be bypassed by any caller path | 03, 08 |

## 3. Inventory — DROP

Deleted from consideration entirely; no port, no reference value. Kept only in the frozen archive.

| # | Item | Location | Reason |
|---|---|---|---|
| D-1 | Dead sessions API (frontend calls to a chat-sessions backend surface that the UI never renders / half-wired) | `d:\Git\medical_bot_backend\app\routers\chat_sessions.py`, `models\chat_session.py`; FE fetch remnants | Chat persistence is redesigned around the LangGraph checkpointer (01 §3, A-4) |
| D-2 | Unused tables: `ConsentRecord`, `Session`, `PasswordResetToken` | `models\consent_record.py`, `models\session.py`, `models\password_reset_token.py` | Modelled but never read/enforced anywhere; consent is FHIR `Consent` with runtime enforcement (03); sessions and resets are Keycloak's job |
| D-3 | Stub password-reset endpoints (accept requests, do nothing — a silent-failure trap for real users) | `app\routers\auth.py` password-reset handlers | Keycloak account flows replace them |
| D-4 | Hand-written dark-mode CSS (`.dark` + `!important` override sheet) | `d:\Git\MedicalBot_FE\app\globals.css` | Token-native theming in `packages/ui`; overrides fight the design system |
| D-5 | Legacy aggregate model module (vestigial duplicate of the split model files) | `d:\Git\medical_bot_backend\models\models.py` | Dead code; the split files (P-7) are the reference copy |
| D-6 | Hard-coded `localhost:8000` rewrite proxy | `d:\Git\MedicalBot_FE\next.config.js` | Gateway + typed `ts-sdk` clients replace ad-hoc rewrites |

## 4. Week-0 security actions (exact steps)

To execute **before S1 day 1** (owners per 11-sprint-plan-phase-a.md §1). Findings context: live Anthropic API key and Neon Postgres credentials sit in plaintext `.env` in `d:\Git\medical_bot_backend`; the face webhook is unauthenticated; a placeholder JWT signing key is in `app\config.py` defaults.

1. **Rotate the Anthropic API key.** Anthropic Console → API Keys → identify the key in `medical_bot_backend\.env` (`ANTHROPIC_API_KEY`) → create replacement key (scoped, low rate limit if the prototype must stay runnable internally) → revoke the leaked key → confirm revocation with a test call (expect 401). Store the replacement only in the new SOPS vault (10-devops-infrastructure.md §5). Check Anthropic usage logs for anomalous consumption since the key's creation; record findings in the ops journal.
2. **Rotate the Neon database password.** Neon console → the prototype project → Roles → reset password for the role in `.env` (`DATABASE_URL`) → if the prototype stays running internally, update its runtime env out-of-band (never re-committed). Review Neon access history for unknown source IPs. Revoke any additional roles/connection strings created ad hoc.
3. **Set a strong `SECRET_KEY` if the prototype keeps running internally.** The JWT signing key defaults to a placeholder string in `d:\Git\medical_bot_backend\app\config.py` — any holder can mint valid tokens. Generate 64 random bytes (`openssl rand -hex 64`), set via runtime env only. This is a stop-gap for the frozen prototype only; the platform uses Keycloak-issued tokens (R-1).
4. **Take the face webhook off any public network.** `POST /api/v1/agent/face-recognized` accepts unauthenticated check-in events. Remove any public DNS/port-forward/tunnel to the prototype backend; restrict to the internal network or shut the deployment down entirely. Confirm with an external scan of previously exposed hosts/ports. Notify the face-service team that the endpoint is retired (§6).
5. **Purge secrets from git history — or accept and contain.** The keys are already burned (steps 1–2 make them worthless); rewriting history on frozen repos is optional. Decision: rotate (mandatory) + freeze; do **not** publish the repos anywhere; record the leaked-then-rotated identifiers in the security log so any future reappearance is recognised as stale.
6. **Archive-tag both repositories.** In each of `d:\Git\medical_bot_backend` and `d:\Git\MedicalBot_FE`: `git tag archive/2026-07-prototype-freeze && git push origin --tags`; set the remote repository to archived/read-only where the host supports it.
7. **Add README deprecation pointers.** Prepend to each README: status FROZEN (date), "superseded by `medagent-platform` — see `docs/solution/00-master-plan.md`", pointer to this document for the salvage map, and an explicit "do not deploy; known security defects" line.
8. **Confirm closure in S1.** W0 items are verified as part of the S1 done-when (11 §2).

## 5. Prototype-flaw → platform-fix traceability

The ten security findings from the prototype audit, and the mechanism (not intention) that closes each:

| # | Prototype finding | Where (prototype) | Platform fix — mechanism | Doc |
|---|---|---|---|---|
| 1 | Open doctor self-registration (anyone becomes a doctor) | `app\routers\auth.py` signup | No self-registration for staff: Keycloak admin-provisioned accounts, role assignment via realm-as-code + admin workflows | 02 |
| 2 | No doctor↔patient authorisation (any doctor reads all records) | all `app\routers\*` CRUD | FHIR authz interceptor enforces role/scope **and** doctor↔patient relationship on every FHIR interaction; not bypassable by any caller path | 03, 02 |
| 3 | JWT signing key is a placeholder default string | `app\config.py`, `app\core\security.py` | Tokens issued/verified only by Keycloak (rotating realm keys, JWKS); services never hold signing keys; gateway validates at edge | 02, 01 |
| 4 | Face webhook completely unauthenticated | `app\routers\agent.py` (`/face-recognized`) | HMAC-SHA256 signature + ±300 s timestamp + idempotency + key rotation via `X-MedAgent-Key-Id`, mTLS where network permits | 05 §3 |
| 5 | `face_consent` modelled but never enforced | `models\patient.py` flag, unread | Consent is a FHIR `Consent` resource checked at runtime (webhook processing + consent interceptor); consent precedes enrolment; revocation destroys the remote template | 05 §2, 03 |
| 6 | In-memory SSE queues break beyond one worker; events lost on restart | `app\routers\agent.py` | notify-service is stateless fan-out over Redis pub/sub — correct by construction at any replica count | 01 §1 |
| 7 | Fake streaming (full completion, then word-split drip) | `app\routers\agent.py` + FE consumption | Real token streaming: LangGraph `astream_events` → AI SDK data protocol → `useChat` | 04 §2.4 |
| 8 | Live secrets committed in plaintext `.env` | `medical_bot_backend\.env` | Vault-only secrets (SOPS/age → cloud SM), gitleaks + push protection in CI, rotation schedule, per-service least privilege | 10 §5 |
| 9 | Password-reset endpoints are silent no-op stubs | `app\routers\auth.py` | Keycloak account-management flows (email via configured SMTP; mailpit in dev); no bespoke credential endpoints exist to stub | 02 |
| 10 | Dual schema mechanism: runtime `create_all` + vestigial Alembic | `app\database.py`, `migrations\` | Alembic-only for `app_db` with CI drift check and `create_all` grep-guard; HAPI exclusively owns `hapi_db` | 10 §9 |

Related non-security debt closed structurally: audit only partially covered (→ interceptor-enforced AuditEvent, NFR-8); localStorage auth and no route middleware (→ OIDC sessions + gateway); 859-line god component (→ decomposed `packages/ui`); no tests/env/i18n (→ CI gates, IaC envs, next-intl scaffold from S1).

## 6. Face-service coordination items

The face-recognition service is external and unchanged (D5); these items need the **face-service team's** action, agreed in the S2 sync (11 §3). Contract detail: 05-face-recognition-integration.md.

| # | Item | What changes for the face-service team | Needed by |
|---|---|---|---|
| C-1 | **Webhook signing rollout** | Sign every event: `X-MedAgent-Signature: v1=HMAC-SHA256(secret, timestamp + "." + raw_body)` + `X-MedAgent-Timestamp` + `X-MedAgent-Key-Id`; retire calls to the old unauthenticated prototype endpoint; agree dual-key rotation procedure (10 §5 schedule) | S2 |
| C-2 | **Enrolment ID mapping** | Adopt the ticketed enrolment flow (`POST /enrolments` with single-use, 15-min, patient-bound ticket; callback with `ext_face_id`); confirm `ext_face_id` is opaque and reissued on re-enrolment | S2 |
| C-3 | **Consent-check behaviour change** | The platform, not the face service, is the consent authority: the service may match anyone enrolled, but the platform short-circuits non-consented events to manual flow — and **revocation triggers `DELETE /enrolments/{ext_face_id}` which must destroy the template and confirm via callback**. Service must not cache or re-create linkage after destruction | S2 (flow), S5 (portal toggle live) |
| C-4 | Event payload contract | Emit the agreed JSON (ext_face_id, confidence, station/facility, event id for idempotency); expect `202` always; retries with same event id are safe | S2 |
| C-5 | PAD / liveness posture | Joint decision on SDK-level liveness for pilot vs certified PAD budget (00 §7.3); Phase A→B graduation criteria per 05 §6 | end S2 |
| C-6 | Network placement | mTLS between service and gateway where the network permits; confirm the service no longer targets any prototype host (§4.4) | S2 |

## 7. Data migration & disposition

### 7.1 Decision: no data migration

The prototype's Neon-hosted Postgres contains development/test data only — synthetic or hand-entered records created during prototype development; there was no production deployment, no consented real-patient intake, and (given finding #2) no defensible provenance for anything in it even if fragments were real. **Decision (ADR S-1): migrate nothing.** The platform starts from versioned Synthea seed data (10 §2.3) in dev/staging, and the pilot begins with **fresh real enrolment at the pilot site** — consent captured first, records created through the audited FHIR path from day one. This is also the cleanest PDPA position: no data of uncertain lawful basis enters the new system (08-security-privacy-compliance.md).

### 7.2 Data-disposition checklist (prototype Neon DB)

Execute during S1; record each step in the ops journal.

1. **Inventory:** connect read-only; list tables and row counts; flag any rows that could plausibly be a real person (names/phones not in known test fixtures). Expected outcome: test data only.
2. **Escalation clause:** if any plausibly-real personal data is found, stop; treat as a PDPA-scoped holding — document, isolate, and dispose per the retention/erasure policy in 08 (lawful-basis review before any action). Do not silently delete real personal data without recording the decision.
3. **Export:** one final encrypted `pg_dump` (age-encrypted) retained solely as an engineering reference for P-7 schema knowledge, held in the team's encrypted archive, retention 6 months then destroy.
4. **Verify:** confirm the export restores in a scratch container; checksum recorded.
5. **Destroy:** delete the Neon project (branches included) after the export is verified and the prototype is fully retired; confirm deletion in the Neon console; note that provider backup expiry lags deletion (record the provider's stated backup-retention horizon).
6. **Close out:** mark the disposition complete in the compliance pack inputs (08); the archived repos' READMEs note that the database no longer exists.

## 8. Decommission timeline

| When | Event |
|---|---|
| Week 0 | Credentials rotated, webhook off public network, repos archive-tagged + README pointers (§4) |
| S1 | Data disposition executed (§7.2); prototype deployments stopped except any strictly internal demo instance (strong `SECRET_KEY`, internal network only) |
| S2 | Face service cut over to the new signed webhook; prototype endpoint retired permanently |
| S3 | Salvage ports P-1…P-5 completed; any remaining internal prototype instance shut down (new workspace demoable end-to-end) |
| S6 | Final check in go-live review: no prototype infrastructure running, Neon project deleted, archive intact |

## 9. Decisions

| ADR | Decision | Rationale | Rejected alternatives |
|---|---|---|---|
| S-1 | No data migration from the prototype DB; fresh Synthea (dev/staging) + real enrolment at pilot | Test-quality data with no consent provenance; migration effort buys risk, not value; cleanest PDPA posture | Selective migration of "real-looking" records (unprovable lawful basis); full lift-and-shift |
| S-2 | Ports are pattern transplants, not code copies | Prototype code carries its architecture's defects (god component, session/auth assumptions); patterns survive translation to Next 16/AI SDK/LangGraph 1.x, code does not | `git mv` + refactor in place; shared library between old and new |
| S-3 | Prototypes frozen with rotate-and-archive, not history rewrite | Keys are dead after rotation; history rewrite on archived repos adds work and destroys audit trail of the leak itself | `git filter-repo` purge; deleting the repos outright (loses P-1…P-8 reference value) |
| S-4 | Keep one encrypted final DB export for 6 months, then destroy | P-7 schema reference occasionally needs real shapes; bounded retention with a destruction date beats indefinite "just in case" | No export (loses reference); indefinite retention (PDPA-hostile) |
| S-5 | Prototype may run internally during S1–S3 as a visual reference only (hardened per §4.3–4.4), then shut down | UX ports (P-1, P-5) go faster against a live reference; hard shutdown date prevents drift into parallel operation | Immediate total shutdown (slows S2/S3 ports); keeping it as a "backup system" (unsafe, unmaintained) |
