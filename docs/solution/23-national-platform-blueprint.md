# 23 · National Platform Blueprint — full-scale design & build map

**Purpose.** Parts 1–7 of the National Solution Document (v3.0) already specify the
*whole* platform. This document is the engineering bridge from that spec to a
build: it (a) states **what is implemented today** vs. what is partial, to-build,
or to-fix; (b) expands the **multi-agent architecture** into a concrete agent +
tool inventory; (c) gives a **design and flow for every Phase-B domain** the spec
calls for (child health, labs, imaging, referrals, scheduling, telemedicine,
voice, registries, analytics, preventive care); and (d) sequences it all into a
**phased plan that integrates the current system** rather than restarting it.

Read it alongside: [00-master-plan](00-master-plan.md), the Phase-A design docs
`01`–`10`, and the as-built records [SECURITY-REVIEW](../SECURITY-REVIEW.md),
[THREAT-MODEL](../THREAT-MODEL.md), [RUNBOOKS](../RUNBOOKS.md),
[BUILD-PLAN](../BUILD-PLAN.md).

Status legend: **✅ done** · **◐ partial** (built but not wired / skeleton) ·
**○ to-build** · **⚠ to-fix** (built but has a known defect).

---

## 1. Where we are today (Phase A, pilot)

A working single-hospital pilot runs end-to-end behind one gateway:

- **Foundations** — HAPI FHIR R4 store, PostgreSQL, Keycloak OIDC + BFF (tokens
  never in the browser), Traefik gateway (HAPI never public), MPI with
  Verhoeff-checksum PHN, transactional audit (outbox → FHIR `AuditEvent`).
- **Doctor workspace** — live queue, patient search, summary card, and a
  **conversational agent** (LangGraph + Claude) over **16 read tools** that cites
  every fact.
- **Clinical safety** — a **deterministic Rx-safety engine** (allergy / interaction
  / dose) with a 100% eval gate; write-back is *draft → screen → e-sign → commit
  → audit*; a BLOCK cannot be signed.
- **Patient portal** — own record, "who accessed my record" log, consent toggle,
  record export (printable + FHIR bundle).
- **Notifications & learning** — email/reminder service; a **governed learning
  loop** (feedback → drift metrics → human-reviewed candidates; never self-modifies
  the safety engine).
- **Ops & assurance** — Prometheus/Grafana golden-signals, dependency-audit CI
  gates, a verified DB restore drill, a compliance pack (threat model + DPIA-lite).

This maps to spec **Phase 0 + Phase 1** and most of the Part-7 sprint plan.

---

## 2. The gap map — spec → status

By spec module (Part 2 FR IDs). This is the honest "what's implemented / what to
build / what to fix" the pilot needs before scaling.

| Module (FR) | Status | Notes |
|---|---|---|
| **Identity / face (FR-1.x)** | ◐ | Manual check-in ✅; opt-out path ✅. Face **SDK not integrated** — enrolment, 1:N match, ISO 30107-3 liveness, edge processing are **○ to-build** (buy an SDK, don't train). Isolated encrypted template store is designed, not built. |
| **Doctor dashboard (FR-2.x)** | ✅ | Queue, summary card (red-flag allergies), search, side-by-side chat done. "Today's follow-ups / pending results" (FR-2.3) ◐ — needs lab/imaging modules first. |
| **AI read/query (FR-3.x)** | ✅ | Auto-summary, NL Q&A, item retrieval, **citations**, allergy/interaction flagging all done. |
| **AI write-back (FR-4.x)** | ◐ | Prescription draft→screen→sign→commit→audit ✅; e-sign gate ✅. Diagnosis (ICD-10/SNOMED) coded picker, notes, vitals, **order labs/imaging**, schedule follow-up are **○** (write path exists; these resource types + tools not yet added). |
| **Patient app / family (FR-5.x)** | ◐ | Record view, consent, access log, export ✅. **Guardian proxy (FR-5.9)**, medication reminders (FR-5.4), booking (FR-5.5), emergency profile (FR-5.7) are **○**. |
| **Administration (FR-6.x)** | ◐ | Roles/realm ✅; audit view ✅. Staff-account admin wrapper, threshold/rule config UI, DSR export/delete workflow **○**. |
| **Lifetime record & child health (FR-7.x)** | ○ | Birth enrolment, SLUDI link, immunization engine, growth curves (WHO), CHDR view, midwife field app — **whole domain to-build** (Phase 3). |
| **National lab network (FR-8.x)** | ○ | LIS hub, barcode/accession, ASTM/HL7 analyzer links, multi-lab routing, critical-value alerts, `DiagnosticReport` notify — **whole domain to-build** (Phase 2). |
| **Imaging & X-ray AI (FR-9.x)** | ○ | PACS/DICOM, AI pre-read, radiologist worklist — **to-build** (Phase 5). |
| **Referrals (FR-10.x)** | ○ | Closed-loop e-referral — **to-build** (Phase 4). |
| **Scheduling & waitlists (FR-11.x)** | ◐ | Appointment reminders ✅ (reminder scan). Waitlists, auto-schedule, national waiting-time view, no-show auto-rebook **○**. |
| **Telemedicine (FR-12.x)** | ○ | Video + guardian/family join + post-consult e-Rx — **to-build** (Phase 4). |
| **Voice AI (FR-13.x)** | ○ | STT dictation, voice commands ("give summary"), TTS — **to-build** (Phase 3+). |
| **Registries / surveillance / analytics (FR-14.x)** | ○ | Auto-registries, notifiable-disease alerts, DHIS2 feed, national dashboards — **to-build** (Phase 5). |
| **Preventive engagement (FR-15.x)** | ◐ | Appointment reminders ✅; the general due-reminder + out-of-range-vitals nudge engine **○**. |
| **FHIR-boundary enforcement** | ⚠ | Authz/consent/**read-audit** interceptors build but are **not enabled** (fail-closed skeleton would break reads — risk R-1). App-layer controls cover it today; promote before multi-facility. |
| **Audit tamper-evidence** | ⚠ | Trail is complete but not yet hash-chained (lands with the interceptor). |
| **Chat interactivity** | ✅ (fixed) | Markdown renderer isolated so it can't disable send/input. |

---

## 3. Multi-agent architecture (expanded)

Spec §3.2 defines **one orchestrator + nine specialists** over a shared,
consent-gated patient context, with fixed guardrails. Today we run a **single
agent** with read + Rx tools. The target is a true orchestrator that routes to
specialists — each specialist is *its own tool-set + policy*, not a separate LLM
call for its own sake.

```
                 Voice / Text  (Sinhala · Tamil · English)
                              │
                     ┌────────▼─────────┐
                     │   Orchestrator   │  understands intent, keeps ONE patient
                     │   (router+scope) │  context, enforces scope, never bypasses
                     └───┬───┬───┬───┬──┘  a specialist's safety check
        ┌────────┬───────┘   │   │   └────────┬─────────┬─────────┐
     Summary   Rx-safety   Lab  Imaging   Schedule  Referral   Reminder   Identity
      agent      agent    agent  agent      agent     agent      agent     agent
        │          │        │      │          │         │          │         │
        └──────────┴────────┴──────┴──── shared tools over ────────┴─────────┘
                    FHIR store · consent · audit · terminology · notify
        ── GUARDRAILS on every action: sign-off before write · cite every fact ──
        ──          act only in consented scope · audit everything            ──
```

### 3.1 Agent + tool inventory (what each agent can *do*)

"Tools" are governed functions the agent may call — patient-scoped, audited,
consent-checked. This is the concrete answer to *"the agent's tools for
documents, images, labs, and learning."*

| Agent | Tools (✅ built / ○ to-build) | Notes |
|---|---|---|
| **Orchestrator** | ○ intent-route, ○ scope-guard, ○ multi-step plan | Today's single agent is orchestrator-lite; formalise routing + a policy that a specialist verdict (e.g. Rx BLOCK) is final. |
| **Summary** | ✅ 16 read tools (summary, conditions, meds, allergies, vitals, labs, imaging, immunizations, encounters, **notes/documents**, procedures, appointments, family/social history, record-overview) | Add ○ **document reader** (parse an attached `DocumentReference`/PDF → cite passages) and ○ **image describer** (see Imaging). |
| **Rx-safety** | ✅ `screen_medication`, ✅ `draft_prescription` (deterministic engine) | Extend dataset to RxNorm/OpenFDA-backed subset; keep engine deterministic. |
| **Lab** | ○ `order_labs` (create `ServiceRequest`), ○ `lab_status`, ○ `summarise_report` (LLM over a `DiagnosticReport` with citations), ○ `flag_critical` | Voice command "give summary" → `summarise_report`. |
| **Imaging** | ○ `order_imaging`, ○ `imaging_status`, ○ `describe_study` (AI pre-read hint — never final), ○ `attach_report` | Radiologist confirms; AI output is advisory. |
| **Schedule** | ○ `book`, ○ `reschedule`, ○ `waitlist_add`, ○ `auto_schedule`, ○ `capacity` | Feeds national waiting-time view. |
| **Referral** | ○ `create_referral`, ○ `referral_status`, ○ `close_loop` | Consent-gated record share with receiver. |
| **Reminder** | ✅ appointment-reminder scan; ○ `due_reminders` (vaccine/screening/refill), ○ `vitals_nudge` | Respects consent + channel preference. |
| **Identity** | ◐ manual check-in; ○ `enrol_face`, ○ `match_face`, ○ `liveness`, ○ `link_sludi` | Buy SDK; templates in isolated store. |
| **Voice (input layer)** | ○ `stt` (Si/Ta/En), ○ `tts`, ○ `voice_command` | English first; native languages hardened next (FR-13). |

**Governed learning loop (spec §3.2, FR-4 governance).** Already built in skeleton:
doctors accept/edit/reject → feedback captured → drift metrics → human-reviewed
candidate datasets. To mature: curate into eval + training sets, **retrain
offline**, re-validate against a clinical test set, **release as versioned models**
with drift/bias monitoring and rollback. Models never self-modify in production.
Applies per capability — prescriptions, lab summaries, imaging pre-reads.

### 3.2 Guardrails (non-negotiable, already the design principle)

1. **Clinician e-sign-off before any write.** 2. **Every answer cites its source
record entry;** out-of-record questions are refused. 3. **Agents act only within
consented scope.** 4. **Every action audited.** 5. **The orchestrator cannot
bypass a specialist's safety verdict** (Rx BLOCK is final).

---

## 4. Domain designs & flows

Each Phase-B domain, with the flow the spec calls for and the FHIR resources it
writes. (Flows are drawn as text so they render anywhere; an illustrated version
can be generated on request.)

### 4.1 Lifetime record & child health (Phase 3 · FR-7)

The record is **born with the child** and follows the citizen for life.

```
Birth in hospital
  → PHN issued (MPI)  +  profile created (Patient)
  → linked to mother's record (RelatedPerson)  +  civil birth registration
  → national immunization schedule auto-generated (Immunization: due dates)
  → guardian proxy granted (RelatedPerson, time-bound → expires at majority)
  → midwife/PHM field app records monthly weight/height (Observation)
       → WHO growth curves plotted; malnutrition (underweight/stunting/wasting) flagged
  → any illness at any facility → same longitudinal record (Encounter/Condition)
  → SLUDI linked when digital ID issued → same record for life
Parent view: digital CHDR (Child Health Development Record) in the app.
```
**Build:** birth-enrolment endpoint (extends MPI); an **immunization engine**
(schedule template → due/given/missed + alerts); a **growth service** (percentiles
vs. WHO tables → deviation flags); a **midwife PWA** (offline-first field capture);
the **CHDR** portal view; guardian-proxy in Keycloak + `RelatedPerson`.
**Resources:** `Patient`, `RelatedPerson`, `Immunization`, `Observation`
(weight/height/head-circ), `Condition`.

### 4.2 National lab network (Phase 2 · FR-8) — the flow you described (Asiri-style)

```
Doctor orders test (ServiceRequest)
  → routed: own hospital lab | regional government lab | (future) approved private lab
  → sample collected → accession number + BARCODE label printed (Code 39 / Code 128)
  → analyzer SCANS barcode, pulls the order over ASTM/HL7 (bidirectional) → runs
  → result returns to LIS hub
       → normal → auto-verified & released
       → abnormal → pathologist validates before release
  → released as DiagnosticReport (LOINC-coded)
       → CRITICAL value → ordering doctor alerted IMMEDIATELY
       → doctor + patient app notified
  → specimen state tracked end-to-end:
       ordered → collected → in transit → received → in progress → resulted → released
  → one collection point can route to MULTIPLE labs; private labs onboard via the SAME interface
```
**AI + voice layer (your ask):** the **Lab agent** exposes `summarise_report` — a
doctor (or patient) can **say "give summary"** (voice-to-text → LLM), and get a
plain-language, **cited** summary of the `DiagnosticReport` with abnormal values
highlighted; the governed learning loop improves these summaries over time.
**Build:** a **LIS hub** service (order routing + state machine), an **accession/
barcode** service (Code 39/128), an **analyzer interface** adapter (ASTM/HL7
LIS2-A2), critical-value rules, LOINC terminology. **Resources:** `ServiceRequest`
+ `Specimen` (order), `DiagnosticReport` + `Observation` (result), `Task` (routing).

### 4.3 Imaging & X-ray AI (Phase 5 · FR-9)

```
Order imaging (ServiceRequest) → study performed → stored as DICOM in PACS
  → AI PRE-READ flags likely abnormalities, prioritises the radiologist worklist
  → RADIOLOGIST reviews & confirms every flagged study (AI is NEVER the final report)
  → final report links to the record (ImagingStudy + DiagnosticReport)
  → doctor + patient notified
```
**Build:** PACS + DICOMweb; an AI pre-read pipeline (bought/hosted model — X-ray
triage first); a radiologist worklist. **Resources:** `ImagingStudy`,
`DiagnosticReport`, `ServiceRequest`.

### 4.4 Referrals — closed loop (Phase 4 · FR-10)

```
Referring doctor creates e-referral (reason, urgency)   [ServiceRequest+Task]
  → receiving institution sees the referral + CONSENTED record slice
  → receiving end schedules the patient → status visible to the referrer
  → treatment done → OUTCOME returns to the referring doctor  (every referral closes)
```
Same-hospital unit or another institution; consent-gated cross-facility read.

### 4.5 Scheduling & waitlists (Phase 4 · FR-11)

Per-institution **waitlists with urgency ordering**; **auto-schedule** from
capacity + urgency (patients notified); a **national waiting-time view** for MoH
planners; reminders (built) + **no-show tracking with auto-rebook**. **Resources:**
`Appointment`, `Slot`, `Schedule`, a waitlist store.

### 4.6 Telemedicine + family (Phase 4 · FR-12)

```
Appointment booked (direct or via referral)
  → video session: patient + doctor; for a CHILD the guardian joins;
    an extra family member may join WITH CONSENT
  → documented as a normal Encounter → e-prescription issued after
  → low bandwidth → AUDIO fallback
```
**Build:** a WebRTC/SFU video service with room-based consented join; guardian/family
join tied to `RelatedPerson` + consent; encounter documentation reuses write-back.

### 4.7 Voice AI (Phase 3+ · FR-13)

STT dictation (English first; Sinhala/Tamil hardened next), **voice commands to the
agent** ("give summary" → spoken/text answer via the LLM), and **TTS** for
patient-facing content (low-literacy support). Voice is the *input layer* to the
same orchestrator — not a separate brain.

### 4.8 Registries, surveillance & analytics (Phase 5 · FR-14)

**Auto-populate registries** (dengue, TB, cancer, CKD, diabetes, configurable)
from coded diagnoses; **notifiable diseases auto-alert the Epidemiology Unit**;
continue **DHIS2 aggregate feed**; **national dashboards** — trend graphs, outbreak
early warning, "how many / where / what's happening", capacity planning; governed
release of de-identified datasets for research. This is the "know the whole system,
spot trends, improve the traditional system" capability — built on the same FHIR
data, read into an analytics store.

### 4.9 Preventive engagement (Phase 6 · FR-15)

Auto-reminders (immunization/screening/follow-up/refill due); chronic-condition
monitoring — **out-of-range vitals trigger nudges** to patient and doctor; all
respect consent + channel preference. Reminders keep patients "at optimal level"
and reduce missed care.

---

## 5. Data model additions (FHIR R4)

Beyond the Phase-A resources, Phase B adds: `RelatedPerson` (guardian/family),
`Immunization`, `Observation` (growth), `ServiceRequest`+`Specimen` (lab/imaging
orders), `DiagnosticReport` (lab/imaging results), `ImagingStudy` (DICOM link),
`Task` (referral/routing state), `Appointment`/`Slot`/`Schedule`, `DocumentReference`
(scanned docs, visit-summary PDFs), and a registries/analytics projection. All keyed
by PHN, all consent-gated, all audited — same spine as today.

---

## 6. Integrating what already exists (never rip-and-replace)

| Existing | Approach |
|---|---|
| **SLUDI** | Identity adapter reserved day-one; PHN↔SLUDI link + biometric auth when the integration opens. |
| **HHIMS (100+ hospitals)** | Exchange-first: an HHIMS↔FHIR connector reads/publishes via the exchange; no replacement. |
| **DHIS2** | Aggregate indicators keep feeding DHIS2; registries add case-level depth. |
| **Private labs (e.g. Asiri)** | Onboard through the **same LIS interface** (HL7/FHIR + Code 39/128) as government labs. |
| **Birth registration** | Birth event triggers profile creation + links the civil record. |
| **PACS / analyzers** | DICOMweb and ASTM/HL7 adapters. |

---

## 7. Phased delivery plan (integrating the current system)

Aligned to spec Part 6. Each phase ships independently and builds on the running
pilot — no restart.

| Phase | What to build | Reuses (already built) |
|---|---|---|
| **0 · Foundation** | ✅ largely done | MPI/PHN, FHIR exchange, consent, audit, terminology base |
| **1 · Pilot workspace** | ✅ done | check-in (manual), workspace, agent (read + safe write), portal |
| **1.5 · Harden now** | ⚠ **fix first:** enable FHIR-boundary interceptors (real logic, side-port tested) + audit hash-chaining; ○ finish write-back resource types (diagnosis/notes/vitals coded); ○ guardian proxy; ○ face-SDK integration | interceptor JAR (built), write path, audit, roles |
| **2 · Lab network** | ○ LIS hub, barcode/accession, analyzer ASTM/HL7, routing, critical alerts, lab agent + `summarise_report` (voice) | ServiceRequest/DiagnosticReport tools, notify, learning loop |
| **3 · Child health** | ○ birth enrolment, immunization engine, growth service, CHDR view, midwife PWA; ○ voice v1 | MPI, Immunization/Observation, portal, offline patterns |
| **4 · Patient flow** | ○ e-referrals (closed loop), national scheduling/waitlists/auto-schedule, telemedicine + guardian/family join | scheduling reminders, consent, encounter write-back |
| **5 · Intelligence** | ○ imaging AI (PACS + pre-read + worklist), registries/surveillance, national analytics dashboards, DHIS2 feed | FHIR data, observability stack, learning governance |
| **6 · Scale & learning** | ○ preventive engagement engine, private hospital/pharmacy onboarding, model-learning maturity (versioned, drift/bias) | reminder scan, feedback loop, integration adapters |

---

## 8. Fix-now list (before scaling)

1. ✅ **Chat interactivity** — markdown isolated (done).
2. ⚠ **FHIR-boundary interceptors** — give them real authz/consent/read-audit logic
   and enable on a side port before swap (risk **R-1**).
3. ⚠ **Audit hash-chaining** — land with the interceptor for tamper-evidence.
4. ○ **Write-back completeness** — coded diagnosis (ICD-10/SNOMED), notes, vitals,
   and the `order_labs`/`order_imaging`/`schedule` tools (unlocks FR-4.6/4.7 and the
   lab/imaging/schedule agents).
5. ○ **Guardian proxy (FR-5.9)** — `RelatedPerson` + Keycloak proxy, time-bound to
   majority (prerequisite for child health + telemedicine family join).
6. ○ **Face SDK** — integrate a certified-liveness SDK; isolated encrypted template
   store (don't train a model for the pilot).

---

*This blueprint is the plan of record for scaling the pilot into the National
Health Platform. It is deliberately build-oriented: every item ties to a spec FR,
a FHIR resource, and a phase, and every "to-build" reuses the spine that already
runs.*
