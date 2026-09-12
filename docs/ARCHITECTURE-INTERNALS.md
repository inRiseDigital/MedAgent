# MedAgent — Architecture Internals ("how it works")

_The deep, mechanical companion to [ARCHITECTURE.md](ARCHITECTURE.md). Where that doc gives the
shape, this one gives the moving parts: the exact database schema, the agent turn lifecycle, the
tools, the audit chains, the auth/consent/check-in flows — grounded in the actual code
(models, routers, agent modules, interceptors) as of 2026-09. If a detail here disagrees with an
older solution doc, this reflects what is actually built._

---

## 1. Data stores — what lives where (precisely)

A crucial mental model: **almost all clinical data lives in FHIR, not in a relational schema.**
`app_db` holds only the small operational tables the platform needs *around* FHIR.

### 1.1 `app_db` (Postgres) — 4 application tables

| Table | Columns | Purpose |
|---|---|---|
| **`patients_mpi`** | `id` (uuid PK), `phn` (str11, unique, indexed), `nic` (str20), `demographics` (JSONB), `ext_face_id` (str128, unique), `face_consent` (bool), `sludi_id` (str128), `created_at`, `updated_at` | Master Patient Index — the local identity/link record. Maps a PHN ↔ face id ↔ SLUDI id; the FHIR `Patient` holds the clinical projection. |
| **`queue_entries`** | `id` (uuid PK), `patient_id` (uuid FK→mpi), `facility_id` (str64, indexed), `state` (enum), `arrival_ts`, `source` (enum) | The live clinic queue. `state ∈ {waiting, in_consultation, done, manual_verification}`; `source ∈ {face, manual}`. |
| **`audit_outbox`** | `id` (uuid PK), `event` (JSONB), `created_ts`, `dispatched` (bool) | Audit outbox — the row is written durably in the local `app_db` transaction, then a background dispatcher drains it to a FHIR `AuditEvent` (§9). NB: the remote HAPI write is NOT in the local transaction (see §7). |
| **`audit_chain_head`** | `id` (int PK=1), `seq` (int), `hash` (str), `updated_ts` | The single-row head of the app-layer tamper-evident audit hash chain (§9). |

**Not in `app_db` — these are FHIR resources** (a common misconception): prescriptions/proposals
(FHIR `MedicationRequest` + verdict extension), consent (FHIR `Consent`), appointments
(`Appointment`/`Slot`), lab orders (`ServiceRequest`), refills (`Task`), consult notes
(`Encounter`+`DocumentReference`), and every clinical fact. The LangGraph Postgres checkpointer is
provisioned-for in `app_db` but **not yet wired** (`main.py` TODO); server-owned Redis threads are
the live multi-turn mechanism (§7).

### 1.2 `hapi_db` (Postgres) — the FHIR store
HAPI's `hfj_*` tables. Resource types in use: `Patient`, `Condition`, `MedicationRequest`,
`AllergyIntolerance`, `Observation` (vitals + labs), `DiagnosticReport`, `Appointment`/`Slot`/
`Schedule`, `Encounter`, `DocumentReference`, `ServiceRequest`, `Task`, `Consent`, `AuditEvent`,
`RelatedPerson`, `Immunization`. core-api reads/writes them through its pooled `FHIRClient`;
the agent's read *tools* query HAPI directly over `fhir_base_url` (see §3), gated at the boundary
by the interceptor under the enforce overlay.

### 1.3 Redis — namespaced, per-service ACL

| Key | Shape | Purpose / lifetime |
|---|---|---|
| `agent:memory:{pid}` | list | Long-term semantic memory per patient (prefs, recurring topics); capped, ~180d TTL, PHI-safe |
| `agent:thread:{cid}` | list | Server-owned conversation thread (last N turns) → server-side multi-turn; the client sends a stable `conversation_id` |
| `agent:telemetry:turns` | list | PHI-free per-turn aggregates (path, latency, tokens) |
| `agent:learning:feedback` | list | PHI-free feedback signals (ratings, accept/reject/override, refusals); question stored only as a hash |
| `authz:{actor}:{patient}` | cached verdict | Care-relationship / consent decision cache |
| `sse:ticket:{ticket}` | short-lived | One-time SSE connection ticket (issued by notify-service) |
| `events:user:{sub}` | pub/sub | Personal notifications (booking/result/refill) → the user's SSE stream |
| `events:checkin:{facility_id}` | pub/sub | Live queue updates → the doctor queue SSE |
| `events:consent:invalidate` | pub/sub | Consent changed → drop cached authz verdicts |
| `face:event:{event_id}` | record | Face-recognition check-in events (from face-sim) |

### 1.4 MinIO
Object store for uploaded reports/images (multimodal) and generated exports (visit summary PDFs).

---

## 2. Anatomy of a chat turn (the real code path)

`POST /api/v1/chat` (agent-service) → an SSE stream. Body: `{messages[], patient_id, audience,
locale, conversation_id, mode}`. Step by step:

1. **Identify + guard.** `require_user` validates the bearer (split-horizon JWKS, §10). Missing
   model key → a clean "not configured" message. `resolve_patient_fhir_id(patient_id)` maps the
   PHN → FHIR `Patient` id.
2. **Load history.** `load_thread(conversation_id)` pulls the last N turns from
   `agent:thread:{cid}` (server-owned — the client need not re-send full history).
3. **Build the grounded context** (`app/agent/context.py`). Fetches, with the caller's bearer,
   `GET /patients/{phn}/summary` + `/brief` from core-api (the consent/authz-checked path), then
   `_render()` produces a compact **cited** block: demographics, SAFETY FLAGS (deterministic),
   active problems/medications/allergies, recent vitals (deduped to latest-per-type, dated),
   recent results, appointments — each fact carrying `[source: Type/id]`. Deterministic dedup +
   human date formatting happen here. Best-effort: no bearer / core-api down → empty context, the
   agent falls back to tools.
4. **Recall memory.** `recall()` reads `agent:memory:{pid}` and renders a "WHAT YOU REMEMBER" block.
5. **Deterministic hooks, in order** (each can short-circuit or augment, none is model-judged):
   - **Emergency escalation** (`escalation.detect_emergency`) — red flag → emit an `escalation`
     widget + 🚨 line, *additively* (§ safety), then continue.
   - **Proactive** (`mode="proactive"`) — an agent-authored grounded greeting/nudge on open.
   - **Overview / 360 fast path** (`_is_broad_overview`) — one tool-free synthesis from context,
     budgeted (`overview_synth_budget_seconds`); on miss → deterministic `_overview_from_context`.
   - **Action fast path** (patient) — `_detect_patient_action` → an instant `confirm-action` card.
   - **Planner** (`_is_multipart`) — stream a `plan-steps` widget, then run the loop.
   - **Specialist lens** (clinician) — `_detect_specialty` injects an expert framing string.
6. **The ReAct loop.** `build_agent(...)` builds a `create_react_agent` with the 24 tools (§3),
   the system prompt (§5), and the grounded context. It streams `stream_mode=["messages","values"]`:
   Anthropic streams the post-tool answer token-by-token via `messages`; OpenAI-compat providers
   (Groq/Ollama) don't stream through LangGraph, so the answer arrives in the final `values` state
   (`final_answer`). Newly-called tools are narrated as `data-status` frames (the reasoning trace).
   Recursion is capped (`agent_recursion_limit=18`); the whole run is bounded
   (`agent_run_timeout_seconds=110`).
7. **Resilience.** Free-text synthesis paths are **buffered + validated** (`_synth_answer`): a
   response that is actually a hallucinated tool-call (`_looks_like_tool_leak`) or empty is
   discarded → grounded deterministic fallback. On a quota/leak/empty ReAct result with context
   present, a grounded tool-free recovery runs before the floor.
8. **Reflect** (`_reflect`) — for a planned multi-part ask that answered cleanly, one bounded critic
   call appends "**On reflection —** …" only if a real plan step was missed.
9. **Answer floor** — the stream is never silent: streamed tokens → non-streaming `final_answer`
   (leak-guarded) → a graceful message. Then `data-citations` + deterministic `data-widget`s
   (safety-alert, record-links) are emitted.
10. **Finalize** (`_finish_log`, async) — `record_turn` (telemetry) + `append_turn` (thread) +
    one structured observability log line naming the path that answered and the work shape.

**SSE frames:** `start` · `text-start` · `text-delta` · `data-status` · `data-widget` ·
`data-citations` · `data-proposals`/`data-cards` (back-compat) · `text-end` · `finish` · `[DONE]`.

---

## 3. The 24 agent tools (`app/agent/tools.py`)

These read tools query **HAPI FHIR directly** (`PatientToolClient` over `fhir_base_url`), patient-
scoped, and **cite** every resource they touch (via `.cite()` → the `sources` list →
`data-citations`). They do **not** currently go through core-api's decision-checked path — the
fail-closed interceptor (under the fhir-enforce overlay) is their boundary control, and
`fhir_headers()` forwards the service key so they're admitted. (The grounding *context* in §2.3 IS
fetched through core-api's consent-checked summary/brief. Routing tool reads through core-api is a
tracked follow-up — see the security review F03.)

- **Record reads (14):** `get_patient_summary`, `get_conditions`, `get_medications`,
  `get_allergies`, `get_vitals`, `get_lab_results`, `get_immunizations`, `get_encounters`,
  `get_clinical_notes`, `get_procedures`, `get_appointments`, `get_family_history`,
  `get_social_history`, `get_record_overview`.
- **Rx (2):** `screen_medication(proposed_drug)` (runs the deterministic engine, returns
  block/warn/pass narratable), `draft_prescription(drug, dose_text)` (stages a verdict card —
  never signs).
- **Generative UI (2):** `present_card`, `render_widget(kind, title, data_json)` — `kind` is
  allow-listed; `confirm-action` and `escalation` are deliberately **excluded** so the model can't
  forge an action/alert.
- **Actions (4):** `request_refill`, `book_appointment`, `start_video`, `order_lab` — each **stages
  a confirm card**; nothing commits until the human taps and a gated core-api route runs.
- **Memory (1):** `remember(note)` — appends a PHI-safe preference/topic to `agent:memory:{pid}`.
- **Web (1):** `web_search(query)` — keyless; PHI-guarded (`safety_guards.sanitize_web_query`);
  results labelled `[web: …]`, never mixed into `[source: …]`.

`PatientToolClient` (`search`/`read`/`cite`) is patient-scoped: it only ever queries the resolved
`patient_fhir_id`, and `fhir_headers()` forwards `X-MedAgent-Service-Key/-Roles:system/-Purpose:TREAT`
when the service key is set (so the fail-closed boundary admits it under ENFORCE).

---

## 4. Grounding + system prompt

`build_system_prompt(audience, locale, context)` composes: persona (patient concierge vs clinician
briefing) + safety rules (never diagnose beyond the record, cite everything, propose-don't-commit)
+ the tool list + the **grounded context block** from §2.3 + the memory block + (clinician) the
specialist lens. The context block is authoritative for what it lists and instructs the model to
**reuse its `[source: …]` citations verbatim** — which is why answers stay grounded even without a
tool call.

---

## 5. LLM provider selection (`app/agent/build.py`)

Provider-agnostic: everything OpenAI-compatible flows through `ChatOpenAI`; Anthropic through
`ChatAnthropic`. Two builders:

- **`build_chat_llm`** — the fast paths + tool-free synthesis. Dispatches on `agent_llm_mode`:
  `stub` (deterministic offline), `openai` (Groq/Ollama/vLLM/etc.), else Anthropic. `reasoning_format=hidden`
  is added **only** when `base_url` is Groq AND the model is a reasoning family (gated so Ollama/
  vLLM/Gemini never receive it). Output capped by `min(agent_max_tokens, llm_openai_max_tokens)`.
- **`build_react_llm`** — the tool loop. Prefers Anthropic (`agent_react_provider=anthropic` +
  key) because Claude streams the post-tool answer; otherwise falls back to the configured model.

Provider swap is config-only (`AGENT_LLM_MODE`, `LLM_OPENAI_BASE_URL/MODEL`, `AGENT_REACT_PROVIDER`)
— see the overlays `docker-compose.ollama.yml` / `docker-compose.vllm.yml`.

---

## 6. Memory & threads (multi-turn)

- **Threads** (`threads.py`, `agent:thread:{sub}:{patient_fhir_id}:{cid}`) — the live mechanism.
  The key is bound to the **verified owner** (the `sub` claim + resolved patient), so a
  client-supplied `conversation_id` alone can never load another user's thread (fixed F03 BOLA);
  each turn appends user+assistant text and `load_thread` returns the last `_MAX_TURNS`.
- **Long-term memory** (`memory.py`, `agent:memory:{pid}`) — a capped list of PHI-safe notes
  (`remember` writes; `recall` reads into the prompt). Patient notes key by patient; clinician
  style-notes key by `clin:<subject>` so a doctor's preferences follow them across patients.
- The Postgres LangGraph checkpointer is a documented TODO, not active.

---

## 7. The write spine + the two audit chains

Every write: `web BFF (attach bearer) → core-api router → decision gate (authz + care-relationship
+ consent) → FHIRClient → HAPI`, with an `audit_outbox` row written durably in the local `app_db`
transaction. **Honest caveat (review F04):** the remote HAPI write and the local outbox row are
NOT one atomic transaction — a local SQL transaction cannot span a remote HTTP write. The outbox
gives *durable-intent + eventual* consistency (the audit is never lost), not cross-store atomicity;
a crash between the FHIR write and recording its outcome needs reconciliation (idempotency keys +
conditional creates are the tracked hardening).

**Audit chain #1 — app-layer dispatcher** (`core-api/app/audit.py`, always on): a background loop
(and `/internal/audit/dispatch`) drains `audit_outbox` → FHIR `AuditEvent`, one at a time, each
hash-chained: `hash = SHA-256(prevHash | canonical_basis(event))`, stored on the `AuditEvent` via
the `audit-hash` extension, with the head in `audit_chain_head`. A **Postgres session-level advisory
lock** serialises dispatch across the loop + the manual endpoint + extra workers, so no two
dispatchers fork the chain. `GET /internal/audit/verify` recomputes and detects tampering. An
undispatched row is retried, never double-written.

**Audit chain #2 — FHIR-boundary interceptor** (`AuditInterceptor.java`, under the fhir-enforce
overlay): HAPI itself writes a complete `AuditEvent` for direct boundary access (incl. reads),
hash-chained and **continued across restarts** (bootstraps the head hash from the store, fail-safe
to genesis). This is the "target design" trail; the app-layer dispatcher is the always-on trail.

---

## 8. Identity, session & authorization flow

1. **Login** — the web BFF runs OIDC against Keycloak; the session (tokens) is server-side, the
   browser holds only a session cookie. Every `app/api/*` route attaches the bearer server-side.
2. **Token validation** — services validate `iss` against the **public** issuer but fetch JWKS from
   the **internal** Keycloak URL (split-horizon), with single-flight JWKS refresh so a cold-cache
   burst can't stampede Keycloak into 401s.
3. **Authorization** — role checks (`require_roles`) + the care-relationship decision service
   (`/internal/authz/decision`), cached in `authz:{actor}:{patient}` and invalidated by
   `events:consent:invalidate`. The **patient portal is self-scoped**: the PHN comes from the
   session claim, never the client body, so a patient can only reach their own compartment.
4. **SSE auth** — a browser can't send a bearer on an `EventSource`, so notify-service issues a
   one-time `sse:ticket:{ticket}`; the stream is opened with the ticket, validated once, then the
   connection subscribes to `events:user:{sub}` (or `events:checkin:{facility}` for the queue).

---

## 9. Consent mechanics

- **Model:** per-purpose FHIR `Consent` — TREATMENT (`TREAT`), RESEARCH (`HRESCH`), MARKETING
  (`HMARKT`) — plus the separate biometric face-recognition consent (`patients_mpi.face_consent`).
- **API:** `GET /patients/{phn}/consent` returns `{face_recognition, purposes:{…}}`;
  `PUT` accepts the legacy `{face_recognition}` or `{purpose, granted}`, writes a scoped Consent,
  audits, and publishes `events:consent:invalidate`.
- **Enforcement:** app-layer today; under ENFORCE the `ConsentInterceptor` masks a resource whose
  subject has an active record-sharing **deny** matching the request's purpose (`X-MedAgent-Purpose`
  → stamped → default `TREAT`). Default-allow + fail-open + the face-recognition exclusion mean no
  read that flows today is newly masked unless an explicit matching purpose-deny exists.

---

## 10. Check-in & the live queue

`face-sim` (or manual reception) → a `face:event:{event_id}` → core-api matches it to
`patients_mpi.ext_face_id` (honoring `face_consent`; no/failed match → `manual_verification`) →
a `queue_entries` row (`state=waiting`, `source=face|manual`) → publishes `events:checkin:{facility}`
→ the doctor queue SSE updates live. The clinician moves a patient `waiting → in_consultation → done`.

---

## 11. Rx-safety mechanics (deterministic, outside the model)

`screen_medication` / `draft_prescription` run the deterministic engine (DDI + allergy + dose vs
the patient's real meds/allergies from FHIR). Verdict:
- **block** → surfaced, and the topology guarantees it can never reach sign-off.
- **warn** → signable only with an explicit override (422).
- **pass** → signable.

On the human tap, `core-api /proposals/prescreen` **re-screens** (defence in depth), then
`/proposals/commit` writes the `MedicationRequest` with the verdict as a FHIR extension + audits.
The DDI dataset is clinician-reviewed and **never** auto-modified.

---

## 12. Self-improvement loop (governed)

`POST /feedback` captures PHI-free signals → `agent:learning:feedback`. `app/learning/analyze.py`
+ `growth.py` mine *recurring* failure patterns (thumbs-down → `summary_qa`, refusals → `refusal`,
rejected/overridden proposals → `rx_safety_review`) into **candidate** golden cases under
`evals/candidates/` (needs_review; deterministic dedup). A hard path-guard forbids writing anywhere
but `evals/candidates/`; `rx_safety_review` is intentionally non-gated so the loop can never inject a
drug-safety verdict into the gate. `GET /api/v1/quality` scores drift vs thresholds. Promotion is a
human PR that must pass `evals/run.py` (38/38) in CI. **Nothing here can change clinical behaviour,
prompts, or the Rx dataset.**

---

## 13. Interceptor internals (`platform/fhir/interceptors/`, under fhir-enforce)

- **AuthzInterceptor** (ENFORCE) — admits a request only with a valid trusted-service credential
  (`X-MedAgent-Service-Key`) + role/scope for writes; **no-trawl** shaping forces a patient
  compartment filter on patient-typed searches (a credential-less or unscoped raw read → 403);
  stamps purposeOfUse for the consent/audit layers. Fail-closed.
- **ConsentInterceptor** (EVALUATE) — per-purpose deny masking as in §9; default-allow, fail-open,
  face-recognition excluded.
- **AuditInterceptor** (PERSIST) — chain #2 in §7.

Activation is env-registered by `docker-compose.fhir-enforce.yml` (not the full application.yaml,
which regressed search); base dev runs without it (app-layer controls gate the real paths).

---

## 14. Failure modes & how the system degrades (by design)

| Failure | Behaviour |
|---|---|
| LLM quota / provider down | Grounded deterministic synthesis from context; overview → sectioned 360; answer floor never silent |
| Model emits a tool-call as text | Detected + discarded before any bytes stream; deterministic fallback |
| core-api / FHIR read fails during grounding | Empty context, agent falls back to on-demand tools (best-effort) |
| FHIR store down at audit dispatch | Outbox row stays undispatched, retried later (never lost, never double-written) |
| Audit interceptor can't reach the store at startup | Chain bootstrap falls back to genesis with a warning; auditing never blocks |
| Consent evaluation error | Fail-open (does not mask) — availability of care over silent denial |
| Keycloak cold cache under burst | Single-flight JWKS refresh prevents a 401 stampede |
| Rx engine uncertain | Never silently passes; block can't be signed, warn needs override |

---

## 15. See also
[ARCHITECTURE.md](ARCHITECTURE.md) (shape) · [ROADMAP.md](ROADMAP.md) (status) ·
[THREAT-MODEL.md](THREAT-MODEL.md) + [SECURITY-REVIEW.md](SECURITY-REVIEW.md) (security) ·
[CLINICAL-VALIDATION.md](CLINICAL-VALIDATION.md) · `docs/solution/` (design intent 00–23).
