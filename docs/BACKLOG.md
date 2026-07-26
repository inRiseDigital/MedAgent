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
- [ ] **0.2 Audit hash-chaining** (tamper-evident).
      *Done when:* altering one audit row fails chain verification.

## Track 1 — Complete clinical write-back (unlocks lab/imaging/schedule agents) ✅
- [x] **1.1 Coded diagnosis** (ICD-10 → `Condition`). Verified: commit → `Condition/1101`, ICD-10 coded, audited; doctor UI (Clinical-entry panel).
- [x] **1.2 Clinical notes** (→ `DocumentReference`). Verified: commit → `DocumentReference/1103`, audited; UI.
- [x] **1.3 Vitals capture** (→ `Observation`, LOINC + vital-signs category). Verified: commit → `Observation/1102`, audited; UI.
- [x] **1.4 Lab / imaging orders** (→ `ServiceRequest`). Verified: lab → `ServiceRequest/1107`, imaging → `ServiceRequest/1108`, audited; UI. (Agent-invoked ordering arrives with the Lab agent 2.6, in live LLM mode.)

## Track 2 — Lab network (first national module)
- [x] **2.1 LIS hub + specimen state machine** (ordered→collected→…→released). Verified: advanced through every state; invalid skip + past-released both 409; each transition audited (`lab_state_change`). core-api `lab` router; state on the ServiceRequest.
- [x] **2.2 Accession + barcode** (Code 128). Verified: collection assigns accession `MA…`, creates a FHIR `Specimen`, and `GET /lab/{id}/label` serves a printable Code128 SVG (44 bars + accession text); label 409 before collection. `python-barcode`.
- [x] **2.3 Analyzer interface** (pull/result keyed by barcode; ASTM/HL7 adapter wraps in prod). Verified: PULL finds order by accession → in-progress; RESULT push → preliminary `Observation` → resulted; wrong-state 409; unknown accession 404.
- [x] **2.4 Result release + critical alert**. Verified: normal potassium 4.2 auto-releases → `DiagnosticReport` (final, Observation→final); critical 6.4 detected `critical`, blocked pending `validated_by`, emits `lab_critical_value` alert, releases after pathologist validation. Reference ranges keyed by LOINC.
- [ ] **2.5 Notify doctor + patient; multi-lab routing.** *Done when:* result in "pending results" + portal; one point → two labs.
- [ ] **2.6 Lab agent `summarise_report`** (voice "give summary" → cited summary). *Done when:* cited, abnormal-highlighted summary (needs live LLM or 0.3 stub).

## Track 3 — Ambient AI + voice (adoption)
- [ ] **3.1 Auto-summary on patient open** (no typing). *Done when:* opening a patient shows an instant cited summary + safety flags.
- [ ] **3.2 Voice dictation (English first)** (speech→note). *Done when:* a spoken note is transcribed into the field.
- [ ] **3.3 Voice command "give summary"** (STT→agent→text/TTS). *Done when:* saying it returns the summary.

## Track 4 — Lifetime record & child health
- [ ] **4.1 Birth enrolment** (PHN at birth, mother link, guardian proxy). *Done when:* newborn profile created; guardian views it.
- [ ] **4.2 Immunization engine** (auto-schedule, due/given/missed alerts). *Done when:* schedule at birth; missed dose alerts.
- [ ] **4.3 Growth monitoring** (weight/height → WHO curves + malnutrition flag). *Done when:* low weight flags underweight.
- [ ] **4.4 Midwife field PWA (offline)** + CHDR parent view. *Done when:* offline visit syncs; parent sees CHDR.

## Track 5 — Patient flow
- [ ] **5.1 e-Referrals (closed loop).** *Done when:* refer → receiver schedules → outcome returns to referrer.
- [ ] **5.2 Scheduling + waitlists + auto-schedule.** *Done when:* waitlist auto-books by urgency; national waiting-time view.
- [ ] **5.3 Telemedicine + guardian/family join.** *Done when:* video runs, guardian joins, e-Rx issued after.

## Track 6 — Intelligence (last)
- [ ] **6.1 Imaging AI** (PACS/DICOM + AI pre-read + radiologist confirm).
- [ ] **6.2 Registries + notifiable-disease alerts + DHIS2 feed.**
- [ ] **6.3 National analytics dashboards** (trends, outbreak early-warning, capacity).

---
**Recommended order:** 0.3 → 1.1–1.4 → 2.1–2.5 → 3.1. Depth over breadth: prove the
pilot + one national module (labs) + ambient AI before widening.
