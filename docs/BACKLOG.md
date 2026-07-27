# Backlog — part-by-part build & test

Living execution list. Each task ships on its own and has a **Done-when** = a real
in-stack test. Work top to bottom. Grounded in the gap map in
[solution/23-national-platform-blueprint.md](solution/23-national-platform-blueprint.md).

Status: `[ ]` to-do · `[~]` in progress · `[x]` done.

## Track 0 — Harden the pilot (first)
- [x] **0.3 Offline/stub LLM mode** — agent testable + demoable with zero API calls.
      *Done when:* chat streams a response with no Anthropic request (`AGENT_LLM_MODE=stub`).
- [ ] **0.1 FHIR-boundary interceptors** (authz + consent + read-audit, real logic, side-port tested).
      *Done when:* grant→200, no-grant→403, core-api down→deny; reads show in the access log.
- [x] **0.2 Audit hash-chaining** (tamper-evident). Each AuditEvent carries SHA-256(prevHash|content); `GET /internal/audit/verify` recomputes the chain. Verified: clean → intact:true (3 events); tamper one event → intact:false, broken_at_seq:3; restore → intact:true.

## Track 1 — Complete clinical write-back (unlocks lab/imaging/schedule agents) ✅
- [x] **1.1 Coded diagnosis** (ICD-10 → `Condition`). Verified: commit → `Condition/1101`, ICD-10 coded, audited; doctor UI (Clinical-entry panel).
- [x] **1.2 Clinical notes** (→ `DocumentReference`). Verified: commit → `DocumentReference/1103`, audited; UI.
- [x] **1.3 Vitals capture** (→ `Observation`, LOINC + vital-signs category). Verified: commit → `Observation/1102`, audited; UI.
- [x] **1.4 Lab / imaging orders** (→ `ServiceRequest`). Verified: lab → `ServiceRequest/1107`, imaging → `ServiceRequest/1108`, audited; UI. (Agent-invoked ordering arrives with the Lab agent 2.6, in live LLM mode.)

## Track 2 — Lab network (first national module) ✅
- [x] **2.1 LIS hub + specimen state machine** (ordered→collected→…→released). Verified: advanced through every state; invalid skip + past-released both 409; each transition audited (`lab_state_change`). core-api `lab` router; state on the ServiceRequest.
- [x] **2.2 Accession + barcode** (Code 128). Verified: collection assigns accession `MA…`, creates a FHIR `Specimen`, and `GET /lab/{id}/label` serves a printable Code128 SVG (44 bars + accession text); label 409 before collection. `python-barcode`.
- [x] **2.3 Analyzer interface** (pull/result keyed by barcode; ASTM/HL7 adapter wraps in prod). Verified: PULL finds order by accession → in-progress; RESULT push → preliminary `Observation` → resulted; wrong-state 409; unknown accession 404.
- [x] **2.4 Result release + critical alert**. Verified: normal potassium 4.2 auto-releases → `DiagnosticReport` (final, Observation→final); critical 6.4 detected `critical`, blocked pending `validated_by`, emits `lab_critical_value` alert, releases after pathologist validation. Reference ranges keyed by LOINC.
- [x] **2.5 Pending results + portal + multi-lab routing.** Verified: released reports appear via `GET /lab/reports` (doctor pending list) and in `summary.results` → a **Lab results card in the patient portal** (critical flagged); orders carry a `target_lab` (own / regional gov / private) — two orders routed to two labs. (Real SMS/push channel reuses notify-service — follow-up.)
- [x] **2.6 `summarise_report`** — DETERMINISTIC cited summary (`GET /lab/reports/{id}/summary`): each analyte with value/reference-range/flag + Observation citation, and a headline (critical/abnormal/normal). Verified: critical potassium → "1 CRITICAL", cited; normal → "within normal limits"; 404 unknown. The Lab agent narrates this in live mode — numbers are never invented (safe by design).

## Track 3 — Ambient AI + voice (adoption)
- [x] **3.1 Auto-summary + safety flags on patient open** (ambient, deterministic-first). `GET /patients/{phn}/brief` + `/rx-safety/review` compute proactive flags — high-risk allergies, drug interactions / allergy cross-reactivity among ACTIVE meds, critical labs — shown as a "Safety flags" card on patient open, no typing/LLM. Verified for Nimal: penicillin allergy + cephalexin↔penicillin cross-reactivity + critical potassium, cited. LLM narrates in live mode.
- [ ] **3.2 Voice dictation (English first)** (speech→note). *Done when:* a spoken note is transcribed into the field.
- [ ] **3.3 Voice command "give summary"** (STT→agent→text/TTS). *Done when:* saying it returns the summary.

## Track 4 — Lifetime record & child health
- [x] **4.1 Birth enrolment** (FR-7.1/7.2/7.8). `POST /patients/newborn`: issues PHN via MPI, creates the FHIR Patient (+ birth-registration id), and a guardian `RelatedPerson` linking the mother with `proxy-full` rights expiring at majority. Verified: Baby Perera (PHN 429…, Patient/1192), guardian→mother Nimal, expires 2044-07-20, searchable + summary loads. (Guardian *portal login* proxy = follow-up.)
- [x] **4.2 Immunization engine** (FR-7.3). `GET /patients/{phn}/immunizations` auto-generates the SL EPI schedule from the birth date with per-vaccine status (given/overdue/due-soon/upcoming) + overdue count; `POST` records a given dose as a FHIR Immunization (audited). Verified for Baby Perera: BCG+OPV overdue at birth; record BCG → given, overdue 2→1.
- [x] **4.3 Growth monitoring** (FR-7.4/7.5). `POST /patients/{phn}/growth` records weight/height as FHIR Observations and assesses against WHO child-growth standards (weight-for-age / length-for-age -2SD, sex-specific, age-interpolated) → flags underweight/stunting (audited); `GET` returns the plottable history with per-point age+flag and the latest deviation flags. Verified: 2.0kg/44cm at birth → underweight+stunted; 6.0kg/61cm at 3mo → clear.
- [x] **4.4 CHDR (Child Health Development Record)** (FR-7.x). `GET /patients/{phn}/chdr` aggregates demographics + immunization schedule + growth history + a consolidated alert list (overdue vaccines + growth deviations) — the single source the clinician panel, parent portal, and midwife view all render. Clinician-side `ChildHealthCard` (immunisation status chips + growth flags + alerts) shown on the patient page for children under 5. Verified: CHDR for Baby Perera returns 1 overdue vaccine + clean growth (latest 3mo measurement healthy).

## Track 5 — Patient flow
- [x] **5.1 e-Referrals (closed loop).** `POST /referrals` (ServiceRequest + Task, destination stamped as a `meta.tag`), `GET /referrals/inbox?facility=` (receiving worklist, active-only by default), `GET /referrals/outbox?patient=` (sent view), `POST /referrals/{task}/act` (accept/reject/start/complete with transition guards). Audited (referral_created/referral_state_change). *Verified* end-to-end: create → inbox (patient name resolved) → accept → complete → active inbox clears; reject flow; illegal transition → 409; outbox tracks status.
  - *Hardening spun out of this task:* fixed a real **audit hash-chain concurrency bug** — two dispatchers (background loop + manual flush) could read the same chain head and mint duplicate sequence numbers (observed: duplicate seq 6 forking the chain). Fix: a Postgres advisory lock serialises `dispatch_once`. Also added configurable **JWT clock-skew leeway** (`jwt_leeway_seconds`, dev=300) after Docker VM clock drift caused false 401s. **Verified** after Docker recovery: 8 concurrent dispatchers → exactly 1 drains all rows, 7 skip cleanly (no 500s), sequences 1–10 contiguous with **zero duplicates**, chain intact. Also hardened `verify_chain`: it depended on `_sort=-_lastUpdated` (which silently returned 0 on a cold search index → a false `intact:true`); it now uses a plain paged read, compares against the server's `_summary=count` (shortfall → `intact:null`, never a false pass), and explicitly flags duplicate sequences (fork signature). Fixed `FHIRClient.search` clobbering a caller's `_count`.
- [x] **5.2 Scheduling + waitlists + auto-schedule.** Native FHIR: `POST /schedule/slots` (free Slots on a per-facility/specialty Schedule), `POST /schedule/waitlist` (Appointment status=waitlist, priority=urgency), `POST /schedule/auto-book` (assigns waiting patients to earliest free slots by urgency then wait time, flips Appointment→booked + Slot→busy), `GET /schedule/waiting-times` (national/per-facility view: median/max wait-days + next free slot). Audited. *Verified:* 2 slots + 3 waiting → the urgent patient (added 2nd) takes the 09:00 slot ahead of an earlier-added routine; FIFO within routine; overflow stays waitlisted.
  - *Deeper audit fix here:* the 5.1 advisory lock stopped **concurrent** forks, but a **stale-head** fork remained — `_chain_head` read the head from a FHIR search (eventually-consistent index), so a drain right after a write could miss the latest event and re-mint its seq (observed: duplicate seq 11, dispatchers not even concurrent). Fixed by moving the chain head into a Postgres `audit_chain_head` row (Alembic 0002), read+advanced in the same transaction that marks each row dispatched. *Verified:* back-to-back interleaved dispatches + 8 concurrent → seqs 1..6 contiguous, intact.
- [ ] **5.3 Telemedicine + guardian/family join.** *Done when:* video runs, guardian joins, e-Rx issued after.

## Track 6 — Intelligence (last)
- [ ] **6.1 Imaging AI** (PACS/DICOM + AI pre-read + radiologist confirm).
- [ ] **6.2 Registries + notifiable-disease alerts + DHIS2 feed.**
- [ ] **6.3 National analytics dashboards** (trends, outbreak early-warning, capacity).

---
**Recommended order:** 0.3 → 1.1–1.4 → 2.1–2.5 → 3.1. Depth over breadth: prove the
pilot + one national module (labs) + ambient AI before widening.
