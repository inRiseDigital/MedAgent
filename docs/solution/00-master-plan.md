# 00 · Master Plan — MedAgent Platform

Version 1.0 · July 2026 · MedAgent Platform (AI Medical Agent System, National Solution v3 → engineering plan v4)
Status: Draft for review

## Executive summary

This document set turns the approved **AI Medical Agent System — National Solution Document v3.0** into an implementation-ready engineering plan. Following a full audit of the two existing prototype repositories and current-state research (July 2026), the decision is a **structured rebuild**: a new monorepo built on national-grade foundations (HAPI FHIR R4 store, Keycloak OAuth2, master patient index, consent manager, immutable audit), with the existing **face-recognition service kept unchanged as an external system integrated purely by API contract**, and deliberate salvage of proven prototype assets (chat UX, agent prompt/tool patterns, schema knowledge). Phase A delivers the pilot-hospital slice in 12 weeks with 2 developers; Phase B modules extend the same foundations to national scale without re-architecture.

## 1. Why rebuild (and what we keep)

An audit of `MedicalBot_FE` (Next.js 14 prototype) and `medical_bot_backend` (FastAPI prototype) against the v3 specification found that **every foundation pillar the spec mandates is absent** — there is no FHIR, no consent enforcement, no audit coverage, no RBAC beyond two hard-coded roles, no doctor↔patient authorisation, and the AI layer is a single read-only ReAct agent rather than the specified guarded multi-agent system. Retrofitting these into the prototype skeleton would cost more than building them correctly and would leave the weaknesses in place.

| Asset | Disposition | Where covered |
|---|---|---|
| Face-recognition service (external, already built) | **Keep unchanged** — integrate via hardened API contract | 05-face-recognition-integration.md |
| Doctor chat UX (streaming, quick prompts, overview cards, face-rec toast/card) | **Port** to new web app | 06-doctor-workspace-frontend.md |
| Agent system prompt, per-patient tool scoping, per-tool DB sessions | **Port** into new agent-service | 04-ai-agent-platform.md |
| SQLAlchemy model/enum design knowledge | **Reference** for FHIR resource mapping | 03-fhir-data-platform.md |
| Login lockout logic pattern | **Superseded** by Keycloak | 02-identity-access-mpi.md |
| Everything else (auth, CRUD API, SSE fan-out, schema mgmt) | **Rebuild** | respective docs |

**Immediate actions regardless of build (week 0):** rotate the Anthropic API key and Neon database credentials currently in plaintext `.env`; take the unauthenticated face webhook off any public network; freeze both prototype repos (archive branch, README pointer to this plan).

## 2. Locked decisions (ADR summary)

| # | Decision | Rationale | Rejected alternatives |
|---|---|---|---|
| D1 | New monorepo `medagent-platform`; prototypes frozen as reference | Clean national-grade foundations; deliberate salvage beats in-place refactor of a weak skeleton | Evolve in place; FE-only keep |
| D2 | HAPI FHIR JPA 8.10.x + PostgreSQL as clinical source of truth from day 1 | Spec-mandated; zero licence cost; proven at 100M+ resources; aligns with Sri Lanka NDHX open-source FHIR direction; no later migration | Custom FHIR-shaped schema + facade later; managed FHIR (sovereignty) |
| D3 | Python 3.12/FastAPI services + LangGraph 1.x agents; TypeScript in web only | Team skill continuity, best AI ecosystem (interrupt-based human-in-the-loop, checkpointing, eval tooling) | TS end-to-end; hybrid split |
| D4 | Phase A = spec Part 7 baseline exactly (12 weeks, 2 devs) | Proven scope maths; every addition threatens the safety work | Adding voice/i18n scope; trimming write-back |
| D5 | Face recognition = external system, API contract only | Already built and working; platform owns consent, audit, and notification; service owns capture/match | Rebuilding in-platform |
| D6 | Next.js 16 LTS + Vercel AI SDK for chat streaming | Research: Next 15 already stale; AI SDK replaces hand-rolled SSE for chat (typed tool-call frames); raw SSE retained for event feeds | Next 14 stay; hand-rolled SSE |
| D7 | Drug safety: self-hosted curated DDI dataset keyed by RxCUI + RxClass/ATC allergy-class screening | NLM interaction API discontinued (2024); DrugBank free checker retired (Mar 2026); sovereignty + offline-safe | Commercial DB now (Phase B decision); prose-mining OpenFDA |
| D8 | Keycloak 26.x with plain OAuth2/OIDC scopes for pilot; SMART on FHIR v2 profiles post-pilot | SMART not native to Keycloak; SPI work is real cost; no third-party apps exist yet in Phase A | Full SMART day 1 |

Full ADRs with context live in each module document's Decisions section.

## 3. Document set

| Doc | Covers | Spec traceability |
|---|---|---|
| 00-master-plan.md (this) | Verdict, decisions, doc map, governance | Part 1 |
| [01-system-architecture.md](01-system-architecture.md) | Layers, monorepo, services, data flows, scalability, environments | Part 3 §3.1, §3.3, §3.5; NFR-1…10 |
| [02-identity-access-mpi.md](02-identity-access-mpi.md) | Keycloak, RBAC, MFA/step-up, break-glass, MPI/PHN, SLUDI adapter | FR-6.x, §4.2, §3.3 |
| [03-fhir-data-platform.md](03-fhir-data-platform.md) | HAPI deployment, resource profiles, terminology, consent manager, audit service | §3.4, FR-4.9, FR-6.3/6.4, §4.3 |
| [04-ai-agent-platform.md](04-ai-agent-platform.md) | Orchestrator, guardrails, write-back sign-off, streaming, eval harness, governed learning loop | FR-3.x, FR-4.x, §3.2, §4.4 |
| [05-face-recognition-integration.md](05-face-recognition-integration.md) | API contract with the existing face service, webhook hardening, consent gate, kiosk flow, PAD/template-protection roadmap | FR-1.x, §4.1 |
| [06-doctor-workspace-frontend.md](06-doctor-workspace-frontend.md) | Next.js 16 app, design system, queue, chat UI, sign-off UX, i18n scaffold, accessibility | FR-2.x, NFR-6/7 |
| [07-patient-portal-pwa.md](07-patient-portal-pwa.md) | Patient PWA, consent controls, access log, reminders, booking, guardian proxy | FR-5.x, FR-15.x |
| [08-security-privacy-compliance.md](08-security-privacy-compliance.md) | PDPA (as amended 2025), biometric ISO 24745, threat model, DPIA, retention | Part 4 |
| [09-integrations-national.md](09-integrations-national.md) | NDHX/NEHR alignment, HHIMS, DHIS2, SLUDI, lab network (Phase B), drug data pipeline | §3.6, Part 5, FR-8.x…FR-14.x |
| [10-devops-infrastructure.md](10-devops-infrastructure.md) | Docker/IaC, CI/CD, observability, backups/DR, secrets | NFR-3/5/9, S1/S6 |
| [11-sprint-plan-phase-a.md](11-sprint-plan-phase-a.md) | 6×2-week sprints refined with salvage tasks and this plan's decisions | Part 7 |
| [12-salvage-migration.md](12-salvage-migration.md) | Exact port list from prototypes, secret rotation, decommission steps | — |
| [agents/](agents/) | One design doc per specialist agent (orchestrator, identity, summary, rx-safety, lab, imaging, schedule, referral, reminder) | §3.2 |

## 4. Phasing (unchanged from spec, restated with decisions applied)

- **Phase A (12 weeks, pilot hospital):** platform spine (S1) → identity & face check-in integration (S2) → doctor workspace + summary agent (S3) → write-back + Rx safety + e-sign-off (S4) → patient PWA + consent + reminders v1 (S5) → hardening, compliance pack, go-live (S6). Detail: 11-sprint-plan-phase-a.md.
- **Phase B (national modules):** lab network (LIS hub, ASTM/HL7 analyzers, barcodes), child health & CHDR, referrals, national scheduling/waitlists, telemedicine, imaging AI, registries/surveillance/analytics, preventive engagement, offline-first rural sync (PowerSync), Sinhala/Tamil voice hardening, HHIMS/NDHX/SLUDI live integrations. Each lands on the same foundations — no re-architecture.

## 5. External timing the plan aligns to (July 2026)

| Event | Timing | Plan response |
|---|---|---|
| SLUDI first digital IDs | Q3 2026, rollout end-2026 | PHN is primary identifier now; SLUDI adapter interface reserved in MPI (02) |
| PDPA full enforcement (Act 9/2022 as amended by Act 22/2025) | expected during 2026 — mid-pilot | Build PDPA-conformant from S1; DPIA in compliance pack (08) |
| NDHX / National EHR procurement (UNOPS, 30 hospitals, FHIR, open-source) | award ~Apr 2026, mobilising now | FHIR R4 profiles + e-Referral shaped for NDHX compatibility (09); engage early, do not build a silo |

## 6. Governance & working rules

- **Team split (2 devs):** Dev A owns platform (FHIR, Keycloak, MPI, audit, infra, gateway); Dev B owns product (web app, agents, PWA). Both own the eval harness.
- **Definition of done:** deployed to staging, tested, documented, demoed. Eval-gate regressions block release like failing tests (04).
- **Clinical safety invariants (non-negotiable, enforced in code):** no AI write without clinician e-sign-off; every agent answer cites its source resource; every read/write emits an AuditEvent; consent checked at runtime on every flow; care is never blocked (manual fallback, break-glass, offline degradation).
- **Document control:** these docs live in the monorepo `/docs`; changes by PR with review; each doc carries a version line.

## 7. Open items (tracked, not blocking)

1. Pilot hospital confirmation needed by week 7 (spec watch-out) — owner: project lead.
2. Clinician time for DDI rule curation and UAT scripts — book by S3.
3. Certified PAD budget decision (SDK-level liveness acceptable for pilot) — decide by S2 with face-service team.
4. NDHX profile alignment conversation — initiate during S1.
