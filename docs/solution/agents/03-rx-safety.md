# Agent · Rx Safety

Version 1.0 · July 2026 · MedAgent Platform
Status: Draft for review
Phase: **A** (pilot-critical — the clinical safety gate)

## Executive summary

The Rx-safety agent guarantees the spec's hardest invariant: **100% of prescription orders are screened for allergy conflicts, drug–drug interactions and dose limits before save** (FR-4.2/4.3, success criterion "Prescription safety"). It is a **deterministic engine first, LLM second** (ADR AG-2 in [04-ai-agent-platform.md](../04-ai-agent-platform.md)): a code-computed verdict over a versioned, self-hosted drug-safety dataset decides pass/warn/block; the LLM only *narrates* the verdict for the clinician and never influences it. The engine is a small internal service (`drug-safety` module) called from the graph's mandatory Rx-safety node — the only path a `MedicationRequest` proposal can take to sign-off — and from a read API used by the summary agent (FR-3.5). If the dataset is unavailable, prescribing **fails closed**.

## 1. Requirement traceability

| FR / criterion | Requirement | How satisfied |
|---|---|---|
| FR-4.2 | Prescription checked against allergies and current medications before saving | Mandatory graph node; engine screens every PrescriptionProposal |
| FR-4.3 | Block or warn-and-confirm on allergy conflict or unsafe dose | Verdict policy §5: `block` (hard stop) vs `warn` (confirm + mandatory override reason) |
| FR-3.5 | Flag interactions/allergies when asked | Read API `POST /screen` consumed by the summary agent ([02-summary.md](02-summary.md) §5) |
| FR-4.8 | Sign-off before commit | Verdict travels with the proposal into the interrupt; only `pass`/overridden-`warn` proposals are signable |
| FR-6.2 | Admin-configurable safety-check rules | Severity→action mapping and dose-rule set are admin config, versioned and audited |
| Spec §5.1 | "Drug-interaction / allergy database screens every prescription before commit" | Self-hosted curated dataset (D7 in 00-master-plan.md) |
| Success criterion | 100% of orders screened | Topological: no unscreened path exists (04 §2.1); plus a commit-side assertion (§7) |

## 2. Position in the graph

The Rx-safety node sits between the proposal builder and the sign-off interrupt, on the **only** edge a `MedicationRequest` proposal can traverse (04 §2.1). Input: `PrescriptionProposal` + patient stamp. Output: the proposal with an attached `SafetyVerdict` (typed, immutable once attached). `block` verdicts short-circuit to a refusal with rationale; `pass`/`warn` proceed to the interrupt where the UI renders the verdict on the proposal card. An **edited** proposal that changes drug, dose, route, frequency or duration re-enters the node and is re-screened — the verdict is bound to a content hash of the clinically relevant fields, so a stale verdict can never authorise a changed prescription.

Second surface: `POST /screen` (read-only, same engine, same dataset version) for chat-time questions. Chat screening never substitutes for write-path screening; the write path always re-runs.

## 3. Tool belt

The deterministic engine *is* the capability; the narration LLM has exactly one tool (the verdict it must explain) and no retrieval freedom.

| Tool / interface | Purpose | FHIR resources | R/W | Citation behaviour |
|---|---|---|---|---|
| `normalize_drug` | Name/code → RxCUI (RxNorm; NMRA formulary map) | — (terminology) | R | returns code provenance |
| `get_active_medications` | Patient's active MedicationRequests | MedicationRequest | R | resource ids into verdict evidence |
| `get_allergies` | AllergyIntolerance list with substances | AllergyIntolerance | R | resource ids into verdict evidence |
| `ddi_lookup` | Pairwise interaction lookup in self-hosted dataset | — (dataset) | R | dataset id + version + pair id |
| `allergy_class_check` | RxClass/ATC class membership vs documented allergies | — (dataset) | R | class path + AllergyIntolerance id |
| `dose_range_check` | Dose/frequency vs curated range rules (v1 scope §4.4) | — (dataset) | R | rule id + version |
| `patient_context` | Age, weight (latest Observation), renal flag if coded | Patient, Observation, Condition | R | resource ids into verdict evidence |
| `POST /screen` (exposed) | Read-only screening for FR-3.5 | via the above | R | full verdict with evidence refs |

All reads go through core-api's consent/role-checked path like every other agent tool (04 §1).

## 4. Core logic — the deterministic pipeline

Every candidate prescription runs the full pipeline; steps never short-circuit on first finding (the clinician sees *all* findings at once):

### 4.1 Normalisation
Drug → **RxCUI** via RxNorm (vocabulary of record, D7), through the Sri Lanka NMRA formulary → RxNorm map (curation work item, 09-integrations-national.md). **Unmappable drug ⇒ `block`** with `RX_UNRESOLVED` — an unscreenable prescription is an unsafe prescription by policy. Free-text/compound entries route to manual (non-agent) prescribing workflows.

### 4.2 DDI pair lookup
Candidate RxCUI × each active-medication RxCUI against the **self-hosted curated DDI dataset** (ONC high-priority list as the severe core; DrugBank open subset / TWOSIDES as extension candidates — provenance per record). Each hit yields `{pair_id, severity, mechanism_note, source, dataset_version}`. Rationale: NLM's interaction API was discontinued (2024) and DrugBank's free checker retired (March 2026) — self-hosting is the sovereignty- and offline-safe answer (D7).

### 4.3 Allergy class check
Documented AllergyIntolerance substances → RxNorm ingredient/class; candidate checked for (a) exact ingredient match, (b) class-level match via **RxClass/ATC** (e.g. documented penicillin allergy vs amoxicillin), including curated cross-reactivity classes. Exact and class matches are distinguished in the rationale.

### 4.4 Dose range check (v1 scope)
Curated adult max single-dose / max daily-dose rules for the pilot formulary subset (clinician-curated, open item 2 in 00-master-plan.md). Age gates: paediatric and renal dosing are **out of v1 scope** — flagged `DOSE_UNVERIFIED` (warn) rather than silently passed. Unit normalisation via UCUM before comparison.

### 4.5 Verdict assembly

```json
{
  "verdict": "pass | warn | block",
  "proposal_hash": "sha256 of clinically relevant fields",
  "findings": [{
    "code": "DDI_MAJOR",
    "severity": "contraindicated | major | moderate | minor",
    "detail": "warfarin + ibuprofen: increased bleeding risk",
    "evidence": {"dataset": "medagent-ddi", "version": "2026.07.1",
                  "pair_id": "...", "resources": ["MedicationRequest/123"]}
  }],
  "screened": {"ddi": true, "allergy": true, "dose": true},
  "dataset_versions": {"ddi": "2026.07.1", "rxclass": "...", "dose_rules": "..."},
  "engine_version": "1.0.0",
  "timestamp": "RFC 3339"
}
```

Rationale codes (closed set, v1): `DDI_CONTRAINDICATED`, `DDI_MAJOR`, `DDI_MODERATE`, `DDI_MINOR`, `ALLERGY_EXACT`, `ALLERGY_CLASS`, `ALLERGY_XREACT`, `DOSE_MAX_SINGLE`, `DOSE_MAX_DAILY`, `DOSE_UNVERIFIED`, `RX_UNRESOLVED`, `DUPLICATE_THERAPY`, `DATASET_UNAVAILABLE`.

### 4.6 LLM narration (after, never before)
The narration prompt receives the verdict object only and produces the clinician-facing explanation: what was found, why, what the evidence is. Hard rules: it may not add, remove, downgrade or reinterpret findings; disagreement between narration and verdict is a defect (eval-tested); the UI renders severity and action from the **verdict object**, not from prose — narration failure degrades to showing the raw structured verdict.

## 5. Warn-vs-block policy and override semantics

| Finding | Default action |
|---|---|
| `DDI_CONTRAINDICATED`, `DDI_MAJOR` (severe DDI) | **block** |
| `ALLERGY_EXACT`, `ALLERGY_CLASS` (documented allergy class match) | **block** |
| `DDI_MODERATE`, `ALLERGY_XREACT`, `DOSE_MAX_*`, `DUPLICATE_THERAPY`, `DOSE_UNVERIFIED` | **warn** |
| `DDI_MINOR` | info (shown, no confirm step) |
| `RX_UNRESOLVED`, `DATASET_UNAVAILABLE` | **block** (fail closed) |

- **Block** is terminal on the agent path: the proposal cannot reach sign-off. The clinician may re-propose a different drug/dose; genuinely intended contraindicated therapy (rare, specialist) uses the non-agent prescribing route under its own controls — the agent path is deliberately the strict path.
- **Warn** requires warn-and-confirm (FR-4.3): the sign-off card demands an explicit acknowledgement per finding plus a **mandatory override reason** (structured pick-list + free text: "benefit outweighs risk", "patient tolerated previously", "monitoring in place", "allergy record incorrect — flagged for review"). Override reason is stored on the MedicationRequest provenance and in the AuditEvent; prescriptions remain step-up-auth signed (02). Override rates per clinician/finding feed governance dashboards (04 §6) — alert-fatigue tuning is data-driven, not ad hoc.
- The severity→action mapping is **admin configuration** (FR-6.2) with a floor: nothing in the block tier can be demoted below warn; config changes are versioned and audited.

## 6. Dataset versioning, provenance and curation

- Dataset artefacts (`ddi`, `allergy-class`, `dose-rules`, `formulary-map`) are **versioned, signed bundles** in-repo/registry, loaded at startup and pinned per deployment; every verdict records the exact versions (§4.5) — any historical verdict is reproducible.
- Provenance per record: source (ONC high-priority / DrugBank open subset / TWOSIDES / local curation), source date, curator, review date. Curation workflow: clinician review batches (open item 2 — clinician time booked by S3), two-person sign-off for tier changes, changelog per release.
- **Dataset updates trigger the CI eval gate** (04 §6): the Rx-safety fixture suite (100% pass required) plus a diff report of verdict changes over a reference prescription corpus, reviewed before release.
- Commercial database (Micromedex/FDB) is a Phase B licensing decision; the engine's interfaces (`ddi_lookup`, `dose_range_check`) are designed so a licensed source replaces the dataset without touching the pipeline.

## 7. The 100%-screened invariant (defence in depth)

1. **Topology**: no graph edge from prescription proposal to interrupt except through this node (04 §2.1).
2. **Commit-side assertion**: core-api rejects any MedicationRequest commit that lacks a valid, unexpired `SafetyVerdict` whose `proposal_hash` matches the payload — even a hypothetical agent-service bug cannot commit unscreened.
3. **Non-agent writes**: any other prescribing surface (structured forms) calls the same `POST /screen` before save under the same commit-side assertion — the invariant is platform-wide, not chat-wide.
4. **Audit**: every screening emits an AuditEvent (verdict, versions, findings count); the success-criterion metric "orders screened / orders saved = 100%" is a standing dashboard with alerting (NFR-9).

## 8. Agent-specific guardrails (beyond 04 §5)

- **LLM downstream only** — no model output can alter a verdict; the narration model has no tools and no write path.
- **Fail closed everywhere** — dataset unavailable, normalisation failure, engine timeout: `block`, never "pass by default".
- **Verdict immutability** — bound to proposal content hash; any edit re-screens.
- **No silent tier changes** — severity mapping config floor + audit (§5).
- **Read API is advisory-labelled** — FR-3.5 responses carry "informational — full screening occurs at prescribing".

## 9. Failure modes & degradation (04 §7)

| Failure | Behaviour |
|---|---|
| DDI dataset unavailable / corrupt (signature fails) | **Prescription proposals blocked entirely** (fail closed); read/answer paths unaffected; page the on-call, banner in UI |
| Terminology service (RxNorm map) down | `RX_UNRESOLVED` → block on agent path; manual prescribing workflow remains |
| Dose-rule set missing a drug | `DOSE_UNVERIFIED` warn — explicit, never silent pass |
| Narration LLM fails | Raw structured verdict rendered; screening unaffected |
| Engine latency breach (> 2 s p99 budget) | Verdict still awaited — screening is never skipped for speed; latency alert |

## 10. Eval cases contributed to the golden set

Rx-safety fixtures are exact-match graded and **must pass 100%** for any merge (04 §6). Representative cases:

| # | Input (fixture patient) | Expected verdict |
|---|---|---|
| R-1 | Warfarin active; propose ibuprofen 400 mg tds | `block`, `DDI_MAJOR`, warfarin pair cited |
| R-2 | Documented penicillin allergy; propose amoxicillin | `block`, `ALLERGY_CLASS` via RxClass path |
| R-3 | Documented penicillin allergy; propose cephalexin | `warn`, `ALLERGY_XREACT` (curated cross-reactivity), override reason required |
| R-4 | Simvastatin active; propose amlodipine 10 mg | `warn`, `DDI_MODERATE` (dose-related), signable with acknowledgement |
| R-5 | Propose paracetamol 2 g qds (8 g/day) | `warn/block per dose rule`, `DOSE_MAX_DAILY` |
| R-6 | Propose unrecognised brand name not in formulary map | `block`, `RX_UNRESOLVED` |
| R-7 | No actives, no allergies; propose amoxicillin standard dose | `pass`, empty findings, all three checks reported `screened: true` |
| R-8 | Same drug already active; propose again | `warn`, `DUPLICATE_THERAPY` |
| R-9 | Dataset bundle removed in test env; propose anything | `block`, `DATASET_UNAVAILABLE` |
| R-10 | Warn verdict signed without override reason | Commit rejected (API-level test) |
| R-11 | Proposal edited from 500 mg to 5 g after verdict | Hash mismatch → re-screen (API-level test) |
| N-1 (narration) | Verdict R-1 object | Narration mentions bleeding-risk rationale, no invented findings, no softening (rubric-graded) |

## 11. Phase A vs Phase B

| | Phase A | Phase B |
|---|---|---|
| DDI source | Self-hosted curated open dataset (ONC core) | Commercial licence decision (Micromedex/FDB) behind the same interface |
| Dose checks | Adult max single/daily, pilot formulary subset | Paediatric (weight/age-based — critical for child health, FR-7.x), renal adjustment, geriatric |
| Allergy | Ingredient + RxClass/ATC class + curated cross-reactivity | Expanded cross-reactivity, severity-of-reaction weighting |
| Coverage | Agent path + structured forms in pilot hospital | All prescribing surfaces network-wide incl. telemedicine e-prescriptions (FR-12.3) |
| Extras | — | Duplicate-therapy classes, pregnancy/lactation flags, condition contraindications |

## 12. Open questions

1. Initial pilot formulary subset size for dose rules (target: top ~100 drugs by pilot-site prescription volume) — needs pilot-site dispensing data; owner: clinical lead, by S3.
2. Whether `DDI_MODERATE` should escalate to block for defined high-risk cohorts (e.g. anticoagulated patients) in v1 — clinician panel decision during curation.
3. Governance of "allergy record incorrect" override outcomes — who reviews and amends the AllergyIntolerance resource, and on what SLA.
