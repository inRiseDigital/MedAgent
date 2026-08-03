# MedAgent — Production Blueprint (Patient + Doctor, Agentic + Telehealth)

_Deep analysis of the conversational-commerce experience and what it takes to make every
flow real, for both the patient app and the clinician cockpit. Grounded in a full audit of
`services/core-api`, `services/agent-service`, `services/notify-service`, `apps/web`, and
`platform/fhir` (Aug 2026)._

---

## 0. The one-paragraph finding

The **backend already has almost every write-path we need** — scheduling, telemedicine
sessions, immunization recording, growth, lab release + cited result summaries, referrals,
and the universal safety-gated `proposals/commit`. What's missing is the **exposure layer**:
(1) a patient **BFF** (`/api/portal/*`) — today only auth/chat/consent/export exist; (2) agent
**action tools** that call those endpoints (today the agent has zero action tools and reads
FHIR directly, bypassing consent/authz); (3) a **generative-UI card protocol** so the agent's
real outputs render as the premium conversational-commerce cards; (4) a **notifications
producer**; (5) a **real video SFU**; and (6) a genuinely new **refill** path. The scripted
concierge is a faithful mock of a system the backend is 70% ready to power for real.

**North-star architecture:** a *supervised, tool-augmented agent* whose every write is a
deterministic core-api call gated by human-in-the-loop confirmation, emitting *typed cards*
the UI renders. "Safety is topology, not prompt" (already the stated 04 principle) — we
activate it rather than invent it.

---

## 1. Patient conversational-commerce flows — inventory & path-to-real

Legend: **Scripted** = hardcoded demo; **Real** = wired to backend; **Backend exists** =
endpoint present but not exposed; **Missing** = must be built.

| # | Flow (concierge) | Today | Backend that exists | To make real |
|---|---|---|---|---|
| 1 | Proactive nudges (OPV overdue, result ready) | Scripted | `GET /patients/{phn}/immunizations` (EPI + status), `/summary`, `/chdr` | Compute due/overdue + latest result server-side; pass as signals → agent tool `get_due_items`/`get_latest_results`; emit **nudge cards** |
| 2 | Explain my result | Scripted (dengue) | `GET /lab/reports/{id}/summary` (deterministic, cited) **+** patient-persona chat agent | BFF `/api/portal/results`; tool `explain_result(report_id)` → **result card** grounded in the real report |
| 3 | What should I avoid | Scripted | agent (general knowledge + `get_medications`/`get_allergies`) | Already agent-capable; render as **advice card** |
| 4 | View result | Scripted | `/summary` results, `/lab/reports` | BFF proxy → **result card** |
| 5 | Book visit / follow-up / vaccination | Scripted receipt | `schedule.py`: `/slots`, `/waitlist`, `/auto-book`, `/waiting-times` (FHIR Slot/Schedule/Appointment) — **dormant** | Add `POST /schedule/book {slot_id}` (patient-scoped, free→busy + booked Appointment); BFF `/api/portal/booking`; tools `list_slots`/`book_appointment`; **slot-picker + confirmation cards** |
| 6 | Refill a medicine | Scripted | **NONE** | Build refill path: `POST /medications/{ref}/refill` → `MedicationRequest{intent:order,status:draft}` **or** a pharmacist-inbox `Task` (reuse referral Task machinery); reuse Rx-safety screen; BFF + tool + **refill-confirm card** |
| 7 | Am I due for anything | Scripted | `/immunizations`, `/growth`, `/chdr`, `/schedule/waiting-times` | tool `get_due_items` → **due-list card** |
| 8 | Who saw my record | Scripted | `GET /audit/access-log` — **REAL, already in Me tab** | tool `get_access_log` → **access-log card** |
| 9 | Invite family / guardian | Scripted | `telemedicine.py` guardian RelatedPerson + single-use join tokens; `/patients/newborn` guardian proxy | BFF + tool; **invite card** (single-use link) |
| 10 | Join by video | Scripted | `telemedicine.py` session lifecycle + tokens — **media is a stub** | Real SFU (§5) + room UI + BFF `/api/telemedicine/*` |
| 11 | Message my doctor | Scripted | referral `Task` machinery (closest fit); no messaging resource | Build a message `Task`/`Communication` endpoint + inbox; BFF + tool |
| 12 | Free-text Q&A | **Real** (agent-first) | patient-persona ReAct agent + read tools + citations | ✅ done — add structured cards |

---

## 2. Doctor cockpit flows — inventory

| Flow | Today | Notes |
|---|---|---|
| Queue (SSE live) | **Real** | `/api/queue` + check-in SSE |
| Patient search | **Real** | MPI search |
| Patient session (cockpit, vitals/lab gauges, imaging) | **Real (read)** | aggregation of summary/brief/chdr/imaging/lab |
| AI chat (cited, inline Rx sign-off) | **Real** | `/api/chat` + `proposals/commit` |
| Clinical entry (dx / vital / note / lab order / imaging order) | **Real write** | `proposals/commit` (safety-gated, audited) |
| Prescription prescreen + e-sign | **Real write** | `proposals/prescreen` + `commit`; block=409, warn=422 override; verdict persisted as FHIR extension |
| Child health (CHDR / EPI / growth) | **Real (read)** | fed by `/chdr` |
| Referrals inbox (accept/reject/start/complete) | **Real write** | `referrals/{id}/act` |
| Dashboard (KPIs, outbreak, capacity) | **Real (read)** | analytics |
| **Scheduling UI** | **Missing** | `schedule.py` exists, no UI/BFF |
| **Telehealth room** | **Missing** | `telemedicine.py` exists, no video/UI |

**The reusable spine for every real write:** BFF token-attach proxy (`getAccessToken`) →
core-api router → `FHIRClient` → `AuditOutbox`. Any new feature (patient or doctor) follows
this exact shape.

---

## 3. The three architectural upgrades (do these and the demo becomes real)

### 3.1 Patient BFF layer — `/api/portal/*`
Today: `auth`, `chat`, `consent`, `export`, `sse/ticket`. Add token-attach proxies:
`results`, `summary`, `appointments`, `booking`, `refill`, `due-items`, `access-log`,
`telemedicine`. Same pattern as `proposals/[action]/route.ts`. Low risk, high leverage.

### 3.2 Agent ACTION tools — routed through core-api (not direct FHIR)
Add write/action tools, each calling core-api with the **caller's bearer** (so consent +
authz + audit are enforced — closing today's direct-FHIR security gap):
`get_due_items`, `get_latest_results`, `explain_result`, `get_access_log`, `list_slots`,
`book_appointment`, `request_refill`, `start_telemedicine`, `message_care_team`.
**Writes are human-in-the-loop:** the tool returns a *proposal card*; the user taps
**Confirm**; a follow-up call commits — mirroring the clinician e-sign model.

### 3.3 Generative UI — a typed card protocol (the unifying idea)
Replace scripted card rendering with **agent-emitted structured cards**. Extend the existing
`data-proposals` SSE pattern into a general `data-card` frame with typed `kind`s:
`nudge | result | advice | due-list | access-log | med-list | slot-picker |
booking-confirm | refill-confirm | telemed-invite`. The frontend renders each kind with the
premium `.mh` components already built. This makes the **exact** conversational-commerce UX
real and data-driven — same cards, now backed by the record — for **both** patient and doctor.

---

## 4. Agentic architecture — recommendation (single vs multi-agent)

**Recommendation: a supervised, tool-augmented agent — not a sprawling multi-agent swarm.**

- **Keep one ReAct agent per turn** for latency and debuggability, but **activate the
  supervisor** (`orchestrator.py`, currently a stub) as an **intent + safety router**: the
  write path must traverse the deterministic Rx gate before any commit ("safety is topology").
- **Specialists are deterministic skills, not chatty sub-agents.** Scheduling, refill,
  immunization/CHDR, lab-interpret, imaging-triage, referral, telemedicine each become a
  **tool backed by the existing deterministic core-api engine**. The LLM narrates and
  orchestrates; determinism and safety live in core-api + `rxsafety` (already true today).
- **Human-in-the-loop via LangGraph `interrupt()`** for every write (book/refill/prescribe)
  → resume on Confirm. Requires the **Postgres checkpointer** (TODO already noted) — which
  also gives **chat history persistence** for free.
- **When multi-agent earns its keep:** parallel specialist reasoning (e.g. a complex clinical
  question that needs lab-interpret + rx-safety + imaging simultaneously) → fan out, then a
  synthesis node. Use it there, not everywhere.

Net: activate `orchestrator.py`, wire `/chat` to the compiled graph, make nodes call the real
agent/engine, add the checkpointer + resume endpoint, and add the action-tool belt.

---

## 5. Video consultation — recommendation

**Do NOT embed Google Meet.** Meet has no proper third-party in-app video SDK (you'd deep-link
out of the app), patient health data would transit Google (PDPA / data-sovereignty problem for
a national system), and you'd lose the guardian single-use-link + FHIR-Appointment model already
designed. **Do NOT use Twilio Video** (Programmable Video is discontinued). **Do NOT hand-roll
WebRTC** (NAT traversal, SFU scaling, recording — months of work).

**Use an SFU that can be self-hosted for sovereignty. Two-step recommendation:**

| Option | Type | Fit | Verdict |
|---|---|---|---|
| **Jitsi Meet** | OSS, self-host | JWT-gated rooms, iframe/External API embed, turnkey | **MVP** — fastest real video; JWT maps to existing single-use tokens |
| **LiveKit** | OSS, self-host or cloud | Modern SDKs (web/iOS/Android), egress/recording, scalable SFU, JWT rooms | **Production** — best control + features |
| Daily.co | Managed | HIPAA, prebuilt+custom, recording | if speed ≫ sovereignty |
| Vonage Video / Chime SDK / Azure Communication | Managed | Mature, regional | fallback |

**Path:** `telemedicine.py` already provisions the FHIR `Appointment` + single-use join tokens
+ guardian RelatedPerson model — replace the stub `media` block with a **Jitsi (MVP) → LiveKit
(prod)** room + JWT; add BFF `/api/telemedicine/*`; build one **room component shared by doctor
and patient** (waiting room, screen-share to show results/X-rays, consented recording →
`DocumentReference`, phone fallback). Data stays on-prem/regional.

---

## 6. Cross-cutting production gaps (full list)

- **Notifications producer** — nothing publishes to `events:user:{sub}`; core-api lacks the
  Redis ACL grant. Add a personal-channel publisher (booking confirmed / result ready / refill
  approved) + grant + promote sms/push adapters beyond logging stubs.
- **Localisation Si / Ta / En** — portal is English-only; national requirement.
- **PWA / offline** — no manifest, service worker, or installability (phone-first).
- **Chat history persistence** — each `/chat` is stateless; solved by the checkpointer (§4).
- **Consent granularity** — one global toggle; needs per-purpose Consent resources.
- **Agent tools via core-api** — currently bypass consent/authz by hitting FHIR directly.
- **Accessibility** — screen-reader labels, focus, large-text, low-literacy voice/read-aloud.
- **Seed data** — no seeded Slots/virtual Appointments; scheduler/telemed demos have no data.
- **Emergency escalation** — persona mentions it; no real triage/nearest-facility action.
- **Profile / PHN onboarding** — demo user has `phn` preset; real linking flow missing.

---

## 7. Prioritized roadmap

**Phase 1 — "make the demo real" (mostly BFF + tools + card protocol, low backend risk)**
1. Generative-UI `data-card` protocol + typed card renderer (unifies scripted look with real data).
2. Patient BFF `/api/portal/*` proxies (results, summary, due-items, access-log, booking).
3. Agent read-action tools: `get_due_items`, `get_latest_results`, `explain_result`, `get_access_log`.
4. Data-driven proactive nudges + real result explanation (kills the dengue fiction).
5. Wire `schedule.py` booking → `list_slots` + `book_appointment` (real appointments).

**Phase 2 — transactions & realtime**
6. Refill endpoint (new) + tool + card.
7. Notifications producer + Redis ACL + sms/push adapters (result-ready / booking / refill).
8. HITL `interrupt()` + Postgres checkpointer (also = chat history).
9. Real video: Jitsi MVP wired to `telemedicine.py`; shared doctor/patient room UI.

**Phase 3 — scale & compliance**
10. Activate the supervisor/multi-agent + specialist skills.
11. Localisation Si/Ta/En; PWA/offline; accessibility.
12. LiveKit production video + consented recording; consent granularity; profile/onboarding.

---

## 8.5 Progress log (2026-08-03)

**Done (real, record-backed):**
- ✅ Patient AI persona (warm, plain-language) + `audience` switch.
- ✅ Agent-first typed questions → live agent reads the real record; citation chips.
- ✅ Agent answers rendered as formatted rich text (markdown), not raw output.
- ✅ Proactive greeting nudges are **real & age-aware** (overdue EPI only for
  children; real latest-result card, critical-aware). Dengue fiction removed.
- ✅ "Explain it simply" / "View result" use the patient's **real** latest result.
- ✅ Summary tab: **real vital trend charts** — new `GET /patients/{phn}/vitals/trends`
  endpoint + `LineFade` tiles; deduped vitals; honest range-bar fallback.
- ✅ Record/Summary rows are **tappable → ask the live agent** (result / med /
  problem / allergy / critical flag), via decoupled window events.
- ✅ Me tab: **real, human-readable access log** (no raw UUIDs).
- ✅ Responsive desktop: sidebar + chat + **at-a-glance right rail**; fixed mobile bar.
- ✅ Dev hot-reload fixed (webpack + polling); patient BFF reads via server components.

**Partial:**
- ⚠️ **Patient BFF (3.1)** — reads flow through server components (`coreApiGet` +
  token); no dedicated action routes yet (booking/refill).
- ⚠️ **Agent read-action tools (1.3/3.2)** — "due items"/"latest result" are
  computed in the page layer, not yet agent tools; agent tools still hit FHIR
  directly (consent/authz-via-core-api still pending).
- ⚠️ **Localisation** — `en/si/ta.json` + next-intl exist, but the patient app
  strings are hardcoded English and there's no in-app language switcher.
- ⚠️ **"Who saw my record"** — real on the Me tab; the concierge chat chip is
  still scripted.

**Not started (still scripted or absent):**
- ❌ Concierge **book / refill / dueCheck / invite / join-video** flows (scripted).
- ❌ **Real booking (1.5)** — `schedule.py` still unexposed.
- ❌ **Refill endpoint (Phase 2.6)** — none exists.
- ❌ **Generative-UI card protocol (1.1/3.3)** — agent still emits text + end-of-
  stream citations/proposals only; no typed `data-card` kinds.
- ❌ **Notifications producer + Redis ACL (§6)** — SSE infra idle for patients.
- ❌ **HITL `interrupt()` + Postgres checkpointer / chat history (Phase 2.8)**.
- ❌ **Real video (§5, Phase 2.9)** — telemedicine media still a stub.
- ❌ **Supervisor/multi-agent activation (Phase 3.10)** — `orchestrator.py` dead code.
- ❌ **PWA/offline**, **consent granularity**, **emergency escalation**,
  **profile/PHN onboarding**, **seeded Slots/Appointments**.

**Quick real wins remaining (data already exists):** make the concierge
`dueCheck` chip use `/immunizations`, and `whoSaw` chip use `/audit/access-log`
— both are already-real endpoints powering other views.

## 8. First concrete step

Phase 1.1 + 1.3 + 1.4 together are the highest-leverage move: they turn the **look** you
already approved into a **real, record-backed** experience without new backend risk. Suggested
order: (a) define the `data-card` schema + renderer, (b) add a `get_due_items` +
`get_latest_results` + `explain_result` tool that calls core-api, (c) make the greeting
compute real nudges, (d) render agent answers as typed cards instead of plain bubbles.
