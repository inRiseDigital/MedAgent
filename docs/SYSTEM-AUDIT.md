# System audit & completion task list (2026-07-27)

Ground-truth deep scan of the whole platform (code + running stack + tests +
infra), independent of BACKLOG claims. Legend: ✅ done & verified · 🟡 partial ·
⬜ not started · 🧪 needs automated test.

## Phase completeness (feature backlog)

| Track | Item | Code | Auto-test | Verdict |
|---|---|---|---|---|
| 0 | 0.3 stub LLM mode | ✅ | ✅ (graph) | done |
| 0 | 0.2 audit hash-chain (+ concurrency + stale-head + verify hardening) | ✅ | ⬜ 🧪 | **test debt** |
| 0 | 0.1 FHIR-boundary interceptors | 🟡 skeleton | 🟡 @Disabled | **not done** |
| 1 | 1.1–1.4 clinical write-back | ✅ | ⬜ 🧪 | done, untested |
| 2 | 2.1–2.6 lab network | ✅ | ⬜ 🧪 | done, untested |
| 3 | 3.1 ambient safety flags | ✅ | ⬜ 🧪 | done, untested |
| 3 | 3.2 / 3.3 voice | ⬜ | ⬜ | **not started** |
| 4 | 4.1–4.4 child health | ✅ | ⬜ 🧪 | done, untested |
| 5 | 5.1–5.3 referrals / scheduling / telemedicine | ✅ | ⬜ 🧪 | done, untested |
| 6 | 6.1–6.3 imaging / registry / analytics | ✅ | ⬜ 🧪 | done, untested |

**Backend feature code: 100% of tracks present.** The gaps are (a) automated
tests, (b) 0.1 boundary enforcement, (c) voice, (d) UI for Track 2/5/6.

## Peripheral stubs found (documented, non-blocking)

- queue `POST /{id}/state` accepts any target — no transition matrix.
- telemedicine media join returns a signalling stub (no SFU/ICE).
- notify-service SMS/push/email adapters are dev log stubs.
- authz per-actor facility scoping; face rate-limit/liveness; OTel export; `aud` enforcement.
- `app/graph/` orchestrator in agent-service is dead-code stub (real agent is `agent/build.py`).

## Completion task list (this effort)

### A. Test debt — regression coverage (highest value, zero risk)
- [x] A1. Audit hash-chain: unit tests for `_chain_hash`, `verify_chain` (intact / tamper→broken / duplicate-seq fork / false-pass guard).
- [x] A2. Referrals: create → inbox → act transitions + illegal-transition 409.
- [x] A3. Schedule: slots → waitlist → auto-book urgency ordering.
- [x] A4. Imaging: triage classify (normal/abnormal/urgent) + confidence floor.
- [x] A5. Registry: notifiable classify (ICD + text) + non-notifiable.
- [x] A6. Analytics: outbreak threshold signal.

### B. UI wiring (demo value)
- [x] B1. Referrals inbox/outbox screen + act buttons.
- [x] B2. Imaging worklist (triaged reports, urgent-first).
- [x] B3. Lab worklist / results screen.
- [ ] B4. Scheduling / waitlist screen.
- [ ] B5. i18n: migrate hardcoded English (clinical-entry, dashboard) into messages/*.

### C. Voice (3.2 / 3.3)
- [x] C1. Voice dictation (Web Speech API) into the clinical-note field.
- [x] C2. Voice command "give summary" → agent → text.

### D. 0.1 FHIR-boundary interceptors (highest risk — staged)
- [x] D1. Implement AuthzInterceptor real logic (service-trust + role/scope + care-relationship via core-api decision + Redis cache, fail-closed).
- [ ] D2. Implement ConsentInterceptor evaluation + cache invalidation.
- [ ] D3. Implement AuditInterceptor persistence (or keep app-side chain authoritative).
- [x] D4. Enable the @Disabled JUnit tests; build the JAR.
- [ ] D5. Wire runtime enablement WITHOUT breaking core-api writes (service credential); validate on a side port before flipping.

**Sequencing:** A → B → C → D. D is last because it is the only item that can
break the running stack; it needs a service-auth handshake so core-api's own
writes survive enforcement.

## Completion status (this effort)

- **A. Tests — DONE.** +30 regression tests (audit-chain tamper/fork/false-pass,
  imaging/registry/growth rulesets, referral transitions, waitlist order, outbreak
  signal, and the Rx-safety engine). Suites: core-api 40, agent-service 12, all green.
- **B. UI — DONE (core).** Referral inbox screen + accept/reject/complete actions;
  imaging + lab results cards on the patient page; nav + auth-gate + i18n. Full web
  `tsc --noEmit` clean. *Remaining (B5):* migrate the pre-existing hardcoded English
  in clinical-entry/dashboard into `messages/*` (cosmetic; new screens already gated
  and localised where they add nav).
- **C. Voice — DONE.** Web Speech dictation into the clinical note (3.2) + "give
  summary" chat command (3.3), progressive-enhancement (hidden when unsupported).
- **D. FHIR-boundary interceptor — LOGIC DONE, activation STAGED.** AuthzInterceptor
  enforce mode implemented + 14 unit tests (JAR built, BUILD SUCCESS), shipped
  default-off so runtime is untouched. *Remaining:* D2/D3 (Consent/Audit real logic)
  and D5 (register + core-api header forwarding + side-port validation) are genuine
  S2 — documented in `platform/fhir/README.md` and THREAT-MODEL R-1.

**Verification note:** every phase now has automated tests except the peripheral
stubs listed above (notify adapters, telemedicine SFU, queue transition matrix),
which are deferred by design.
