# 11 · Sprint Plan — Phase A (12 weeks, 2 developers)

Version 1.0 · July 2026 · MedAgent Platform
Status: Draft for review

## Executive summary

This plan refines spec Part 7 (6 × 2-week sprints, S1–S6) into an engineering-ready schedule reflecting the locked decisions (00-master-plan.md §2) and this document set. Scope is the spec baseline exactly (D4): platform spine → face check-in integration → doctor workspace + summary agent → write-back + Rx safety + e-sign-off → patient PWA → hardening and go-live. The largest deltas from the spec's own sprint table: S2 is **integration with the existing external face service** (D5) — no SDK or template-store work — and S1 absorbs the week-0 prototype security actions, secrets vault, and NDHX engagement. Team split per spec §7.3: **Dev A owns platform** (FHIR, Keycloak, MPI, audit, gateway, infra), **Dev B owns product** (web app, agents, PWA); both own the eval harness. Definition of done throughout: deployed to staging, tested, documented, demoed (00 §6).

## 1. Working rules (spec §7.3, extended)

- Every sprint: tests in CI, documentation as you build (runbooks by whoever builds the component), Friday demo, backlog grooming.
- Definition of done: **deployed to staging, tested, documented, demoed** — not merely merged. Eval-gate regressions block merge like failing tests (04-ai-agent-platform.md §6, 10-devops-infrastructure.md §3.3).
- Clinical safety invariants are non-negotiable and enforced in code from the sprint they land (00 §6): no AI write without e-sign-off; every answer cites its source; every read/write emits AuditEvent; consent checked at runtime; care never blocked.
- Cross-training rule (bus factor): each sprint, each developer does at least one reviewed task in the other's territory; PR review is always cross-owner.

### Week 0 (before S1 day 1 — hours, not days)

| # | Action | Owner | Detail |
|---|---|---|---|
| W0-1 | Rotate leaked prototype credentials (Anthropic key, Neon DB password) | Dev A | exact steps: 12-salvage-migration.md §4 |
| W0-2 | Take the unauthenticated face webhook off any public network | Dev A | 12 §4 |
| W0-3 | Freeze both prototype repos (archive tag, README deprecation pointer) | Dev B | 12 §4 |
| W0-4 | Book clinician time: DDI rule curation (needed S3–S4) and UAT (S4) | Project lead | spec watch-out; 00 §7 |
| W0-5 | Open pilot-site confirmation track (deadline: week 7) | Project lead | spec watch-out |

## 2. Sprint S1 · Spine (weeks 1–2)

**Goal:** a running, secured, observable platform skeleton — create and search a patient via the gateway with a valid token, audit entries visible, CI green, secrets in the vault. (Spec S1 "done when", extended with vault + week-0 closure.)

| Dev A (platform) | Governing docs |
|---|---|
| Monorepo scaffold per canonical layout (apps/services/platform/packages/infra/docs); repo hygiene: branch protection, gitleaks, push protection | 01 §2, 10 §3.6 |
| Compose stack: full local stack incl. HAPI, Keycloak, Postgres (two DBs, per-service creds), Redis, MinIO, mailpit, Traefik, face-sim stub; profiles (default/observability/seed/test) | 10 §2 |
| HAPI FHIR 8.10.x container + **interceptor skeletons** (authz, consent, audit — wired, deny-by-default, logic lands S1–S2); network isolation behind gateway | 03-fhir-data-platform.md, 01 §1 |
| Keycloak 26.x realm-as-code (keycloak-config-cli): all 11 spec-actor roles defined in the realm JSON from day 1 — six active in pilot (doctor, nurse, receptionist, admin, patient, guardian); dormant: midwife_phm, lab_tech, radiologist, moh_planner, plus the break_glass modifier (02 §3) — clients per service, MFA policy stub | 02-identity-access-mpi.md |
| Gateway (Traefik): TLS, route map, JWT validation at edge, rate-limit baseline | 01 §1, 02 |
| MPI v1 in core-api: PHN issuance (format + check digit), demographic dedup candidate matching, projection to FHIR `Patient`, SLUDI adapter interface reserved (empty implementation, contract defined) | 02 |
| **Audit interceptor v1**: AuditEvent on every FHIR read/write through the gateway path; append-only storage decisions applied | 03, 08-security-privacy-compliance.md |
| Secrets vault: SOPS+age structure, per-env files, CI decrypt for deploy, rotation runbook stubs | 10 §5 |
| CI/CD: path-filtered lint/typecheck/unit jobs, ts-sdk contract check, image build + Trivy, deploy dev→staging auto | 10 §3 |

| Dev B (product) | Governing docs |
|---|---|
| Next.js 16 app scaffold: route groups (workspace / portal / kiosk), next-intl i18n scaffold day 1 (D4 — strings externalised, en only), design tokens seeded from prototype Tailwind palette | 06-doctor-workspace-frontend.md, 12 §1 |
| `packages/ui` bootstrap + `packages/ts-sdk` generation pipeline from core-api OpenAPI | 01 §2, 10 §3.2 |
| Auth flow: Keycloak OIDC login (Authorization Code + PKCE), session handling, role-gated routing — replaces prototype localStorage auth entirely | 02, 06 |
| Synthea seed script (Sri Lanka-adjusted config, PHN injection, demo-patient subset with consent + `ext_face_id` stubs); seed job in compose | 10 §2.3 |
| First vertical slice UI: patient search against MPI + FHIR via gateway (proves the whole path) | 02, 06 |
| Alembic baseline for `app_db` (no `create_all` anywhere; CI guard) | 10 §9 |

**Also in S1 (project lead + Dev A, timeboxed):** initiate the NDHX profile-alignment conversation (00 §7.4, 09-integrations-national.md) — the platform must not become a silo the national programme rejects.

**Done when:** `docker compose up` gives the full stack seeded with Synthea data; creating and searching a patient works only with a valid Keycloak token, and both operations produce visible AuditEvents; unauthenticated and direct-to-HAPI access are rejected; CI runs all jobs and deploys to staging; zero secrets in any repo file; W0-1…3 confirmed closed.

**Risks:** HAPI interceptor development is Java in a Python/TS team — timebox a spike in week 1 and keep interceptor scope minimal (see §8 watch-outs); two-DB discipline needs the CI guards in from day 1 or drift starts immediately.

## 3. Sprint S2 · Identity & face check-in (weeks 3–4)

**Goal:** live face check-in against the **existing external face service** loads the right synthetic patient into the workspace; opt-out and manual fallback work; consent gates the flow platform-side. **No face SDK, template store, or matching work exists in this sprint** — the service is built; this is contract implementation (D5, 05-face-recognition-integration.md).

| Dev A (platform) | Governing docs |
|---|---|
| Inbound webhook endpoint: HMAC-SHA256 signature (`X-MedAgent-Signature`/`-Timestamp`/`-Key-Id`), ±300 s freshness, idempotency, dual-key rotation support, 202-async processing | 05 §3 |
| Enrolment linkage: ticketed enrolment flow, `ext_face_id` ↔ PHN binding in MPI, `DELETE /enrolments` on consent revocation with destruction-confirmation callback | 05 §2 |
| **Consent gate**: FHIR `Consent` (face-recognition scope) checked at webhook processing; Redis-cached decisions with invalidation; consent precedes enrolment, always | 03, 05 §2 |
| Check-in pipeline: `ext_face_id` → patient → threshold policy → arrival queue (`app_db`) → Redis publish → AuditEvent; unknown-ID alerting | 01 §4.1, 05 §3 |
| notify-service v1: Redis pub/sub → SSE fan-out; **SSE ticket auth** (short-lived, single-use ticket issued via authenticated API, since `EventSource` cannot carry headers); reconnect/backoff semantics | 01 §1, 05, 02 |
| Face-service team sync #1: HMAC rollout, key rotation, enrolment/destruction API agreement, consent-check behaviour change | 12 §6, 05 §8 |

| Dev B (product) | Governing docs |
|---|---|
| Kiosk route: check-in screen states (recognised / not recognised — see reception; the latter covers both below-threshold and silently-dropped consent-off events, which are indistinguishable at the kiosk per 05 §3), receptionist manual-verification queue view | 05, 06 |
| **Manual fallback UI**: receptionist search (name / PHN / phone) → confirm identity → enqueue; never blocks care | FR-1.5/1.6, 05 §5 |
| Doctor-side check-in UX: live queue updates via SSE, FaceRec toast/card port from prototype (real connection-state indicator, not decorative) | 05 §5, 06, 12 §1 |
| Enrolment UX in portal scaffold: consent capture → enrolment ticket → face-service handoff → confirmation | 05 §2, 07-patient-portal-pwa.md |
| Integration tests: signed/unsigned/replayed webhook, consent-off silent drop (`AuditEvent(consent_denied)`, nothing surfaced), end-to-end face-sim → SSE | 10 §3.4 |

**Done when:** a face-sim (and, if the service team is ready, real face-service) event for a consented demo patient appears in the doctor queue in < 300 ms platform-side; the same event for a revoked-consent patient is **dropped silently** — `AuditEvent(consent_denied)` emitted, suppression-list entry pushed, nothing appears in any queue or view (05 §3); a below-threshold event for a consent-active patient routes to manual verification; forged/replayed webhooks are rejected and alerted; enrolment and revocation round-trip with the (stub or real) service; zero biometric data anywhere in the platform.

**Risks:** face-service team availability is an external dependency — the HMAC + enrolment contract must be agreed this sprint even if their implementation lands later (face-sim keeps us unblocked); PAD/liveness budget decision due with this sprint (00 §7.3).

## 4. Sprint S3 · Doctor workspace & summary agent (weeks 5–6)

**Goal:** a doctor works from the live queue, opens a patient, and asks the agent questions that return **cited, correct** answers; the eval harness runs in CI before any write-back exists (AG-6: the gate precedes the risk).

| Dev A (platform) | Governing docs |
|---|---|
| Queue service hardening: arrival ordering, state transitions, day rollover; quick stats endpoints (seen, open tasks, results pending) | FR-2.1/2.5, 02 |
| FHIR summary query set (NFR-2 < 2 s): tuned `$everything`-scoped queries, per-encounter cache; HAPI performance pass (pool, indexes) | 03, 01 §5 |
| Authz interceptor completion: doctor↔patient relationship enforcement (fixes prototype flaw #2 by construction) | 03, 02, 12 §5 |
| Observability build-out: OTel across gateway→services→FHIR, Grafana dashboards (golden signals, HAPI, SSE health), alert rules v1 | 10 §6 |
| Eval infrastructure in CI: gate job, thresholds, baseline tracking, PR reporting | 04 §6, 10 §3.3 |

| Dev B (product) | Governing docs |
|---|---|
| Workspace UI: live queue, **summary card** (photo, age, blood group, red-flagged allergies, active meds), record + chat side-by-side, manual search | FR-2.x, 06 |
| **Orchestrator v1 + summary agent**: LangGraph graph, FHIR read tools (citation-emitting), refusal behaviours; prototype system prompt as v0 seed, per-patient tool scoping and per-tool session patterns ported | 04, agents/00 + 02, 12 §1 |
| Chat UI port from prototype: streaming chat, quick prompts, overview cards — rebuilt on **AI SDK** (`useChat`, typed frames; real token streaming replaces fake word-drip) | 06, 04 §2.4, 12 §1 |
| Citation UX: every answer chip links to the source FHIR resource view | FR-3.4, 06 |
| English STT v1: dictation into chat input (server-relayed whisper-class DictationProvider per 06 — browser Web Speech API rejected, 06 W-9); Si/Ta deferred to Phase B per D4 | FR-13.1, 06 |
| **Eval golden set v1 (≥150 cases)** with Dev A: summary QA over pinned Synthea seed, citation faithfulness, injection probes, refusal cases | 04 §6 |

**Done when:** spec S3 criterion — doctor asks "last 3 visits / current meds / allergies" and gets cited, correct answers; a question about another patient is refused; eval pass-rate is tracked per commit and a seeded regression demonstrably blocks a merge; summary loads < 2 s on staging data; dashboards live.

**Risks:** golden-set grading needs clinician sanity-review time (booked W0-4); LLM cost visibility must be in dashboards *this sprint* or S4–S6 budget surprises follow; **pilot site must be confirmed by week 7** — escalate now if not on track.

## 5. Sprint S4 · Write-back, Rx safety & e-sign-off (weeks 7–8)

**Goal:** full consult end-to-end on staging: check-in → review → propose → unsafe prescription blocked → signed → FHIR resources + audit. The clinical safety gate (spec §2.4) becomes real.

| Dev A (platform) | Governing docs |
|---|---|
| Commit path in core-api: proposal → FHIR transaction (Condition, MedicationRequest, Observation, DocumentReference/notes) with provenance + AuditEvent | 03, FR-4.9 |
| **Self-hosted DDI dataset load**: curated open interaction set keyed by RxCUI (D7), versioned in-repo, load job, update procedure; NMRA formulary → RxNorm mapping v1 (top pilot-formulary drugs first) | 09, agents/03-rx-safety.md |
| Allergy class screening: RxClass/ATC drug-class matching service | agents/03 |
| **Step-up auth** for prescription sign-off (Keycloak ACR/LoA flow); break-glass design reviewed (pilot = audited manual-override procedure, 60 min default / 4 h ceiling per 02 §6.1; automated workflow Phase B) | 02, 04 §2 |
| DDI dataset in eval gate: change to dataset triggers Rx-safety fixture run (100 % required) | 04 §6, 10 §3.3 |

| Dev B (product) | Governing docs |
|---|---|
| Structured proposal flow in the graph: **interrupt-based sign-off** (LangGraph `interrupt()`), proposal cards (diagnosis with ICD-10 picker, note, vitals, prescription), edited/rejected re-entry, expiry on encounter close | 04 §2, FR-4.1–4.8 |
| Rx-safety agent node: deterministic screen (allergy + interaction + dose limits) *before* the card renders; warn vs block UX; orchestrator cannot bypass (topology, not prompt) | agents/03, 04 §2 |
| Sign-off UX: proposal card with safety verdict, step-up prompt for Rx, signed/edited/rejected capture (feeds the learning loop) | 06, 04 §6 |
| Vitals entry (BP, sugar, weight, temp) via chat proposal and direct form | FR-4.5, 06 |
| Eval set growth: Rx-safety fixtures (known DDI/allergy cases — 100 % hard requirement), write-back proposal correctness cases | 04 §6 |
| **UAT scripts** drafted with pilot clinicians (W0-4 time): scripted consults covering safe/unsafe paths | 08, spec S4 |

**Done when:** spec S4 criterion — a full consult runs end-to-end; a prescription conflicting with a recorded allergy or a known interaction is blocked/warned before the clinician ever sees a commit button; nothing reaches FHIR without a signed resolution; step-up is required for Rx sign-off; audit trail covers the whole chain; Rx-safety eval fixtures pass 100 % in CI.

**Risks:** highest-stakes sprint — safety logic must be deterministic code, not prompts (04 §2 principle); DDI curation quality depends on booked clinician review; **hard check: pilot site confirmed by end of week 7** or go-live scope re-plans (§8); step-up flows in Keycloak are fiddly — spike early in the sprint.

## 6. Sprint S5 · Patient PWA & notifications (weeks 9–10)

**Goal:** spec S5 criterion — a patient sees their records, receives a visit-summary SMS, and toggling face consent changes check-in behaviour on the next arrival.

| Dev A (platform) | Governing docs |
|---|---|
| notify-service completion: SMS adapter (local gateway) + web push; channel preference + consent respected (FR-15.3); delivery status tracking | 07, FR-15.x |
| Patient-facing access: patient role scopes in Keycloak, patient↔record authz in interceptors, **personal access log** endpoint from AuditEvent (FR-5.8) | 02, 03 |
| Booking v1 backend: slots, book/reschedule/cancel, FHIR `Appointment` | FR-5.5, 02/03 |
| Visit-summary auto-send pipeline: encounter close → summary render → SMS/push per preference | 07 |
| Backup/DR completion: pgBackRest both DBs, object-storage versioning, off-site copy; first restore rehearsal (dry run before the S6 formal drill) | 10 §7 |

| Dev B (product) | Governing docs |
|---|---|
| Patient portal PWA: records, prescriptions, lab results, visit summaries; installable, WCAG 2.1 AA checks in CI | FR-5.3, 07, NFR-6 |
| **Consent toggle wired to the face flow**: portal toggle → FHIR Consent update → cache invalidation → enrolment destruction call on revoke (05 §2) → check-in behaviour change | FR-5.2, 05, 07 |
| Access-log view ("who viewed my record") | FR-5.8, 07 |
| Booking v1 UI | FR-5.5, 07 |
| **Reminder agent v1**: follow-up due + medication reminder generation, consent/channel-aware, via notify-service | FR-15.1, agents/08-reminder.md |
| Guardian proxy model surfaced read-only (full proxy management is Phase B; the data model supports it from S1) | FR-5.9, 07 |

**Done when:** a demo patient logs into the PWA, sees their consult from S4's flow, receives the visit summary by SMS (mailpit/SMS-sim on staging), views their access log; toggling consent off causes their next face-sim event to be dropped silently (`AuditEvent(consent_denied)`, suppression-list entry, nothing surfaced — 05 §3) and triggers template destruction on the (stub) face service; reminders fire on schedule and respect channel preference.

**Risks:** SMS gateway procurement/contract for pilot lead time — start in S4; scope discipline: portal is read + consent + booking v1, nothing more (capacity note §9); PWA offline behaviour is *graceful degradation only* in Phase A (NFR-5 full offline-first is Phase B).

## 7. Sprint S6 · Hardening, compliance & go-live (weeks 11–12)

**Goal:** spec S6 criterion — real patients, with consent, at the pilot site, with the safety evidence to prove it.

| Dev A (platform) | Governing docs |
|---|---|
| Security pass: OWASP ASVS-scoped review, dependency audit, **RBAC review** (role-by-route matrix verified), rate limits tuned per route, security headers, TLS config verified | 08, 10 §3.5 |
| Performance vs NFRs: full k6 suite (check-in burst, chat concurrency, record load, soak) on staging; fixes; NFR-1/2 evidence recorded | 10 §8, 01 §5 |
| **Formal restore drill** (both DBs, from IaC, timed vs RTO 4 h) + backup verification; drill report filed | 10 §7.3 |
| Monitoring completion: all dashboards provisioned, alert rules + on-call-lite rota live, runbook set complete (10 §7.4 list) | 10 §6–7 |
| Degradation paths tested: face-service outage → manual mode; LLM outage → agent-unavailable workspace still functions; network loss procedures | 04 §7, 01 §5 NFR-5 |
| Pilot deploy: IaC-built pilot environment, protected-environment approval flow, go-live + rollback rehearsal | 10 §4 |

| Dev B (product) | Governing docs |
|---|---|
| **Compliance pack** with project lead: DPIA-lite, threat model (incl. biometric flow), consent-record export, audit-coverage report, AI-governance summary (eval evidence, model pin history) | 08, 04 §6 |
| UAT execution with pilot clinicians; defect burn-down; sign-off capture | S4 scripts, 08 |
| **Pilot training**: receptionist (check-in + manual fallback), doctor (workspace, chat, sign-off, feedback buttons), patient enrolment desk procedure; training materials + paper-fallback procedure | 05 §5, 06, 07 |
| Clinician **feedback loop live**: signed/edited/rejected + 👍/👎 capture flowing to weekly eval-case curation | 04 §6 |
| UX hardening: empty/error/loading states, accessibility fixes from CI axe backlog, i18n string completeness check (en) | 06, NFR-6/7 |

**Done when:** security review findings closed or risk-accepted in writing; k6 evidence meets NFR-1/2/3 targets; restore drill within RTO; compliance pack delivered and reviewed; pilot staff trained; first real, consented patients checked in and consulted at the pilot site; on-call-lite rota active.

**Risks:** UAT findings arriving late — front-load UAT to week 11 day 1; go-live is contingent on the site confirmation made by week 7; PDPA full enforcement may land mid-pilot — compliance pack must be filed as if enforcement is active (00 §5).

## 8. Watch-outs

Spec §7.5 retained, plus new items arising from the locked decisions:

| # | Watch-out | Mitigation / owner |
|---|---|---|
| 1 | **Pilot site confirmed by week 7** or S6 go-live is unrealistic | Project lead; tracked from W0-5; week-7 go/no-go checkpoint in S4 |
| 2 | **Clinician curation time** for DDI rules, golden-set review, and UAT | Booked in week 0 (W0-4); if it slips, Rx-safety scope narrows to the pilot formulary's top drugs — never to weaker checks |
| 3 | **PAD/liveness budget** — certified PAD costs money; SDK-level acceptable for pilot | Decision with face-service team by end of S2 (00 §7.3); Phase A→B graduation criteria in 05 §6 |
| 4 | **Bus factor** (2 developers) | Runbooks and docs are DoD items, not optional; weekly cross-training rule (§1); secrets escrow (10 §5) |
| 5 | **HAPI interceptor Java skills** (new, from D2) — the team is Python/TS; authz/consent/audit interceptors are Java against HAPI internals | Week-1 spike; keep interceptor logic thin (decisions computed in core-api-owned policy where feasible, interceptor enforces); budget review time; fallback: gateway-level enforcement for a subset while interceptor matures (A-2 notes the APISIX option) |
| 6 | **NDHX engagement in S1** (new, from 00 §5) — national EHR programme mobilising now; late alignment risks profile rework | Conversation opened in S1; FHIR profiles shaped for NDHX compatibility (09); revisit at each sprint review |
| 7 | **Face-service team dependency** (new, from D5) — HMAC signing, enrolment API, and destruction callback need their work | Contract agreed in S2 even if implementation lags; face-sim stub keeps every sprint demoable; coordination checklist in 12 §6 |
| 8 | **LLM cost drift** — agent usage cost invisible until dashboards exist | Cost dashboard mandatory in S3; per-encounter cost tracked; escalation model config-gated (04 §4) |

## 9. Honest capacity note (spec §7.5, restated)

This plan fits 2 developers × 12 weeks **only because infrastructure is reused, not rebuilt** — HAPI, Keycloak, Traefik, LangGraph, AI SDK, the existing face service — and because scope additions are refused (D4). If the team drops to one developer, the honest options remain: a ~5-month timeline, or reducing S5 to a read-only patient portal. Any scope addition must displace something visible on this plan.

## 10. Explicitly deferred to Phase B

Deliberately deferred — not forgotten — each lands on the spec Part 6 roadmap and 09-integrations-national.md:

- Lab network: LIS hub, barcode/accession, ASTM/HL7 analyzer interfaces, multi-lab routing (FR-8.x)
- Generic order proposals (FR-4.6, OrderProposal → ServiceRequest) — the proposal schema exists from day 1; the route is enabled Phase B (04, agents/04)
- Native mobile apps (PWA first, per spec §7.1)
- Telemedicine incl. guardian join (FR-12.x)
- Imaging AI / PACS integration (FR-9.x)
- Registries, surveillance, national analytics dashboards, DHIS2 feed (FR-14.x)
- HHIMS exchange connector; NDHX/NEHR live integration (alignment starts S1, integration is Phase B)
- Live SLUDI integration (adapter interface reserved in MPI from S1; SLUDI IDs issue from Q3 2026)
- Sinhala/Tamil voice hardening and UI translations (i18n scaffolding ships S1; en-only strings in Phase A)
- Full offline-first rural operation (PowerSync bidirectional sync); Phase A ships graceful degradation only
- SMART on FHIR v2 app-launch profiles (plain OAuth2/OIDC scopes in Phase A, per D8)
- Guardian proxy management UI (Phase A is read-only proxy access; data model present from S1; full lifecycle incl. transition-at-majority is Phase B, FR-5.9)
- Commercial drug-database licensing decision (Micromedex/FDB) — D7 keeps pilot on the curated self-hosted dataset
- Certified PAD SDK procurement (pilot runs face-service SDK-level liveness per watch-out 3)
- Break-glass automated workflow (designed in 02/08; pilot uses the audited manual-override procedure — 60 min default / 4 h ceiling per 02 §6.1)
- Kubernetes / national-scale infrastructure moves (10 §11)

## 11. Decisions

Choices this plan itself makes; everything else inherits from the locked decisions in 00 §2.

| ADR | Decision | Rationale | Rejected |
|---|---|---|---|
| SP-1 | Week-0 actions absorbed into S1 (executed before day 1, verified in the S1 done-when) | Hours of work, not days (12 §4); a formal week 0 invites schedule slip; S1's gate forces confirmed closure | Standalone week-0 sprint; deferring rotation/freeze into S1 proper |
| SP-2 | Interceptor-fallback strategy: keep interceptor logic thin (decisions computed in core-api policy, interceptor enforces), with gateway-level enforcement as fallback for a subset while Java skills mature (§8 watch-out 5) | 2-dev Python/TS team against HAPI Java internals is the plan's largest skills risk; the fallback keeps sprints shippable without weakening the invariants | Blocking S1/S3 on full interceptor maturity; abandoning interceptors for gateway-only enforcement (bypassable from inside the network, 03 F-1) |
| SP-3 | Break-glass in pilot = audited manual-override procedure (60 min default / 4 h ceiling per 02 §6.1); automated workflow ships Phase B | The automated flow is UI + policy work that would displace safety-critical S4 scope; audit coverage and time-bounding are identical either way | Automated break-glass in Phase A (capacity); no break-glass at all (care must never be blocked) |
| SP-4 | Guardian proxy is read-only in Phase A; full proxy lifecycle (incl. transition-at-majority) is Phase B | Data model lands in S1 so Phase B is additive; proxy-management UX needs governance decisions not yet made (FR-5.9) | Full proxy management in S5 (capacity, §9); omitting the data model until Phase B (migration cost) |
