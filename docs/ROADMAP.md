# MedAgent — Consolidated Roadmap (single source of truth)

_Supersedes the scattered plan set as the one place to track status. Cross-refs:
[BUILD-PLAN.md](BUILD-PLAN.md) (Phase 0/A/B build tracker), [PRODUCTION-BLUEPRINT.md](PRODUCTION-BLUEPRINT.md)
(conversational-commerce, mostly shipped), the Jarvis plan + task list
(`~/.claude/plans/snuggly-inventing-shamir.md`, `jarvis-tasks.md`), and the "Pilot to Nation"
4-horizon delivery plan (published as an Artifact). Living status lives here._

Legend: ✅ done & verified · 🔨 in progress (current build sweep) · 🧱 code/adapter built,
**needs an external dependency to go live** (licence, auditor, trial, or a real national system) ·
⏭️ deferred with rationale.

---

## The honest frame
The platform is **pilot-complete**: the full clinical loop (grounded cited agent, deterministic
Rx safety, fail-closed FHIR data layer, consult sessions with write-back, orders, multimodal,
patient + doctor surfaces, self-hosted sovereign LLM option) is built, verified, and running.
What remains is the leap to **national production**. Some of that is pure code (done/doing here);
some is **externally gated** — it can have its code, adapters, and simulators built here but cannot
be "live" without a licence, an accredited auditor, clinical trials, or an actual national system
to connect to. Those are marked 🧱 with exactly what unblocks them — never claimed as live.

---

## Sweep log — 2026-09-06 ("complete the rest")
Completed & committed this sweep (each verified):
- ✅ **vLLM production overlay** (`docker-compose.vllm.yml`) — server-GPU self-hosting with
  guided decoding; config-only swap. Compose validated.
- ✅ **Audit hash-chain continued across restarts** — bootstrap re-derives the head hash from
  the store; fail-safe to genesis. Maven BUILD SUCCESS, 27 tests.
- ✅ **Observability alerts + perf harness** — prometheus alert rules (6, promtool-valid) +
  k6 `chat-concurrency.js`/`soak.js` (the two S6 scenarios).
- ✅ **Self-improvement loop** — auto eval-set growth (governed, human-confirm) + `/api/v1/quality`
  drift endpoint. Eval gate stays 38/38.
- ✅ **National integration facades + simulator** (NDHX/SLUDI/HHIMS) — feature-flagged, verified
  end-to-end against the sim.
- ✅ **SNOMED CT adapter** — licensed-server client + non-authoritative offline subset; never
  guesses a code (unknown+unlicensed → 503).
- ✅ **Security residual risks R-1/R-3 narrowed** to reality; **clinical-validation protocol**
  written (harness done, execution externally gated).
- ✅ **Consolidated this ROADMAP.**
- 🔨 **Emergency escalation** + **per-purpose consent** — in progress (parallel agents).
- ⏭️ **OTLP traces/logs** — left as next-pass (metrics + dashboards + alerts already deliver
  strong observability; distributed tracing is the incremental add).

---

## 1 · Core platform & agent — ✅ DONE
- ✅ Monorepo, Docker stack (12 services), Postgres/Redis/MinIO/Keycloak/Traefik/HAPI FHIR
- ✅ Identity spine (OIDC BFF, split-horizon JWKS, roles/clients), live queue, MPI search
- ✅ Grounded, cited ReAct agent (patient + clinician personas); deterministic Rx-safety engine
  (block can never be signed) OUTSIDE the model; generative-UI widget protocol (14+ widgets)
- ✅ Jarvis P1–P7: widgets, memory, HITL actions, web search, proactivity, design unification,
  doctor chat-centric + governed self-learning
- ✅ Horizon 0 (harden): threads/observability, PHI/consent trust surface, **fail-closed FHIR
  interceptors live** (Authz ENFORCE, Consent EVALUATE, Audit PERSIST), telemetry + eval gate 38/38
- ✅ Horizon 1 (depth): doctor consult session + FHIR Encounter/DocumentReference write-back,
  orders & receipts + lab ordering, multimodal (image+PDF+extraction+voice-confirm), planner+reflect,
  specialist lens
- ✅ Data-quality: deduped/sectioned 360 profile, human dates; tool-call-leak guard
- ✅ Self-hosted sovereign LLM (Ollama + Qwen2.5-7B, GPU) — config-only swap; 🔨 **vLLM server
  overlay** for 70B on server GPUs with guided decoding (this sweep)

## 2 · Agent execution model
- ⏭️ **Promote the dormant LangGraph supervisor graph to the real `/chat` path** — the value
  (plan→do→self-check "think-itself") is ALREADY delivered by the planner/reflect functions +
  reasoning trace on the safety-proven single-ReAct path. Promoting the graph is a pure topology
  change and the **highest-risk edit to the working `/chat`**; it stays deferred to an isolated,
  regression-tested pass rather than a "do everything" sweep. Rationale over rush — the felt
  capability is not blocked by this.
- ⏭️ Postgres LangGraph checkpointer (server-owned Redis threads already give durable multi-turn;
  full checkpointer needs the `langgraph-checkpoint-*` dep + rebuild) — pairs with the above.

## 3 · National integrations — 🧱 facades + simulator built; live needs the real systems
- 🔨 **NDHX / SLUDI / HHIMS adapters** — real httpx clients against the §09 spec, feature-flagged
  OFF, with a **local simulator** so they're testable end-to-end. Point them at the actual national
  endpoints + credentials to go live. (this sweep)
- 🧱 Lab network (LIS/HL7/ASTM), Imaging (PACS/DICOMweb), DHIS2 surveillance feed, notifiable-disease
  registry — need the external systems; adapters follow the same facade+sim pattern.
- 🧱 **SNOMED CT** — licence-gated. Build the terminology-service adapter + a small subset/stub;
  full value-sets need the national SNOMED licence.

## 4 · Production assurance (Horizon 3 / S6)
- 🔨 **Audit hash-chain DB-continued across restarts** (was per-process) — tamper-evident chain now
  survives restarts (this sweep)
- 🔨 Observability: OTLP traces/logs → Tempo/Loki + alert rules (metrics + dashboards already live)
- 🔨 Perf: chat-concurrency + soak k6 scenarios (record-load already passing)
- 🔨 CI merge gate: automate dep-audit (pnpm + pip-audit) as a required check
- 🧱 **Security certification** — code-level residual risks (R-1/R-3) closed + docs finalized here;
  the certificate itself requires an **accredited external auditor**.
- 🧱 **Clinical validation** — build the validation/eval harness + protocol; sign-off requires
  **clinicians and a trial**, not code.

## 5 · Self-improvement loop (governed)
- ✅ Feedback capture (PHI-free), drift metrics, human-reviewed candidate generation
- 🔨 **Auto eval-set growth** (failure patterns → candidate golden cases, human-confirm) +
  **drift/quality endpoint** (pass-rate proxies, thresholds → `degraded`) (this sweep)
- ⏭️ Shadow/A-B evaluation, CI eval-gate for prompt/tool changes, self-tuning ops — next pass
- Governance invariant: the Rx-safety engine + dataset are **never** auto-modified; promotion is a
  clinician-reviewed PR that must pass the eval gate.

## 6 · Product polish
- ✅ PWA/offline shell, En/Si/Ta localisation, notifications producer, Jitsi MVP video, consent panel
- 🔨 Consent granularity (per-purpose Consent), emergency escalation/triage tool, profile/PHN
  onboarding (this sweep, after national workstream frees core-api)
- ⏭️ LiveKit production video + consented recording, full accessibility pass, offline-first sync
  (PowerSync/RxDB) — next pass

---

## What "complete the rest" means, precisely
This sweep completes every item marked 🔨 with a passing verification, and builds the code/adapters
for every 🧱 item so it is **ready to connect** the moment its external dependency exists. The ⏭️
items are deferred **on purpose** with the rationale above — chiefly the supervisor-graph refactor,
whose value is already realized and whose risk to the working `/chat` warrants its own tested pass.
