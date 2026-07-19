# 08 · Security, Privacy & Compliance

Version 1.0 · July 2026 · MedAgent Platform
Status: Draft for review

## Executive summary

This document specifies the security, privacy, and compliance programme for the platform: conformance with the **Personal Data Protection Act No. 9 of 2022 as amended by Act No. 22 of 2025**, whose full enforcement is expected **during 2026 — mid-pilot**, so the platform is built PDPA-conformant from Sprint 1 rather than remediated later; the biometric-data posture (architectural isolation — biometric data never enters the platform — plus the ISO/IEC 24745 and ISO/IEC 30107-3 requirements the platform imposes on the external face service); a STRIDE threat model over the main assets and flows; the concrete controls catalogue (encryption, secrets, rate limiting, supply chain, WAF); tamper-evident audit; AI governance per spec §4.4; break-glass under the care-is-never-blocked invariant; retention and destruction per record class; and the DPIA and S6 compliance pack. Traceability: spec Part 4 (§4.1–§4.4), FR-6.3/6.4, NFR-8/NFR-10, success criterion "100% of reads and writes logged, tamper-evident".

Traceability map:

| Spec item | Section here |
|---|---|
| §4.1 Biometric data handling | §3 |
| §4.2 Access, authentication & audit | §4 (STRIDE), §5 (controls), §6 (audit), §8 (break-glass) |
| §4.3 Regulatory alignment | §2 (PDPA), §7.5 (device/CDS posture), §9 (retention) |
| §4.4 AI safety controls | §7 |
| FR-6.3 audit review, FR-6.4 DSR handling | §6, §2.3 |
| NFR-8 auditability, NFR-10 data protection | §5, §6 |
| S6 compliance pack | §10 |

## 1. Governance frame

- **Roles (to be contractually fixed before real-patient go-live, S6 gate):** the pilot hospital / Ministry of Health is the **data controller** for patient data; Rise Tech Village operates the platform as **processor** (or joint controller for the MPI — counsel to determine under the amended Act; the DPIA records the conclusion). The external face service operates as a **sub-processor** under a written processing agreement (05 §6).
- **DPO:** a Data Protection Officer is designated before processing real patient data (PDPA DPO obligation; health-scale processing plainly qualifies). Pilot: one named DPO covering Rise Tech Village with a hospital-side privacy focal point. The DPO owns the ROPA, DPIA, breach register, and DSR log.
- **Statutory referencing note:** obligation names below follow the 2022 Act; **section numbering is to be verified by counsel against the Act 22/2025 consolidated text** before the compliance pack is issued — the amendment changed commencement and Authority arrangements, and this document must not misquote a moving target.
- Security invariants already fixed elsewhere and assumed here: nothing reaches HAPI FHIR except through the gateway with a validated token, and the FHIR pipeline carries authorisation, consent, and audit interceptors (01 §1, 03); the agent never holds broader access than its clinician (04 §2.2); biometric data never enters the platform (05).

## 2. PDPA conformance mapping (Act 9/2022 as amended by Act 22/2025)

Full enforcement is expected during 2026 — i.e. **while the pilot is live**. The platform therefore treats PDPA obligations as launch requirements, not roadmap items. Conformance mapping:

| PDPA obligation | Platform conformance | Where implemented | Phase |
|---|---|---|---|
| **Lawful basis for each processing purpose** | Purpose register (part of ROPA) maps every flow to a basis: clinical care → provision of healthcare / vital interest, reinforced by recorded consent at registration; face check-in → **explicit, revocable consent** (special-category biometrics — consent is the only acceptable basis); reminders/notifications → consent + channel preference (FR-15.3); registries & national analytics → public-interest basis under MoH governance mandate (Phase B, documented before activation); research datasets → governance-approved de-identification (FR-14.5, §9) | core-api consent manager, 03 | A |
| **Consent conditions (informed, specific, withdrawable, demonstrable)** | FHIR `Consent` resources with full version history and provenance; consent capture UI states purpose, scope, and withdrawal path in Sinhala/Tamil/English (translations Phase B, English + staff-assisted A); withdrawal takes effect at the next runtime check (Redis cache invalidation, 01 §4.3); demonstrability = consent export in the compliance pack (§10) | 03, 07 | A |
| **Special-category data (health + biometric)** | Heightened handling: explicit consent for biometrics; biometric templates never enter the platform (§3); PHI minimisation in all egress paths including LLM prompts (04 §4); DPIA mandatory (§10); access limited by role + care relationship + consent at the FHIR interceptor | 03, 04, 05 | A |
| **Data subject right of access** | Patient portal: view records (FR-5.3) and personal access log of who viewed the record (FR-5.8); staff-mediated path for patients without portal accounts (admin DSR console, FR-6.4) | 07 | A |
| **Right to data portability / export** | PDF download/share (FR-5.6) plus structured FHIR JSON export (Patient `$everything`, consent-filtered); DSR export produced within the statutory response period (working target: 21 calendar days, tightened when the Authority's rules fix the period) | core-api export job, 07 | A |
| **Right to rectification** | Clinical correction workflow: FHIR resources are amended by versioned update with `AuditEvent` — clinical records are corrected, never silently rewritten; demographic corrections via MPI with dedup re-check | 02, 03 | A |
| **Right to erasure (qualified)** | Erasure honoured where no overriding retention duty exists: face template destruction at the face service with confirmation callback + linkage cleared (05 §2), portal account deletion, operational data purge. Clinical records are subject to statutory/clinical retention (§9); where erasure is refused, the refusal basis is recorded and communicated — this is PDPA-conformant, and the DSR log evidences it | core-api DSR module (FR-6.4) | A |
| **Breach notification to the Data Protection Authority** | Breach runbook (§10): detect → contain → assess → notify the Authority within the prescribed period (working assumption **72 hours** pending the Authority's rules) → notify affected data subjects where risk of harm is significant → post-incident review. Breach register maintained by the DPO | 10 (runbooks), DPO | A |
| **DPO designation** | Named DPO before real-patient processing; contact published in the portal privacy notice and `security.txt` | §1 | A |
| **Cross-border transfer restrictions** | Transfer register: (1) **Anthropic API (USA)** — clinical prompt content is PHI-minimised (only consented, clinically necessary fields; no direct identifiers beyond what the clinical task requires), processed under enterprise no-training data terms, with a documented transfer assessment; ADR SEC-3 records the posture and the Phase B regional-hosting review triggered if the Authority issues adequacy/instrument rules that the current arrangement cannot meet. (2) SMS via local aggregators — no cross-border PHI (09 §12). (3) Hosting — pilot in-country or in an agreed region; Phase B targets government infrastructure per NDHX direction (01 §6) | 04 §4, 09 | A |
| **Records of processing (ROPA)** | Maintained by the DPO from S1; generated partly from the purpose register and data-ownership table (01 §3) | DPO | A |
| **DPIA for high-risk processing** | Large-scale health + biometric processing is squarely high-risk: DPIA-lite in the S6 compliance pack; full DPIA before Phase B national rollout (§10) | §10 | A→B |
| **Processor contracts** | Written agreements with the face service, SMS aggregator, cloud/host, Anthropic (commercial terms), each covering PDPA processor duties, sub-processing, and breach cooperation | §1 | A |

## 3. Biometric data handling (spec §4.1)

### 3.1 The architectural invariant

**The platform never receives, stores, or transits biometric templates, embeddings, images, or video frames.** Face recognition is an existing external service integrated purely by API contract (05). The platform holds only the opaque, revocable `ext_face_id` linkage and a `FaceCheckinEvent` log. This makes spec §4.1's "isolation" requirement architectural rather than procedural: a full compromise of every platform database yields **zero biometric data**. Edge processing (FR-1.8) is the face service's concern and is encouraged by the same isolation.

### 3.2 Requirements imposed on the face service (contract, tracked here)

05 §6 defines the contract; this document owns compliance tracking and the graduation gate. Summary of the security schedule:

| Requirement | Pilot (Phase A) | National (Phase B) | Standard |
|---|---|---|---|
| Template protection | Encrypted templates, isolated store, keys in KMS, **no raw image retention** after enrolment (quality frames deleted post-template) | Full **ISO/IEC 24745** conformance: **irreversibility** (template cannot reconstruct the face), **revocability** (compromised template replaceable — new `ext_face_id` on re-enrolment, 05 §2), **unlinkability** (templates from different deployments cannot be correlated). Face embeddings are demonstrably reconstructible, so encryption-at-rest alone is *insufficient*: require **cancelable transforms (e.g. PolyProtect)** or **homomorphic-encryption matching**, assessed by an independent reviewer | ISO/IEC 24745 |
| Presentation-attack detection | SDK-level passive liveness acceptable; result reported per event and policy-gated platform-side (05 §3 step 6) | **ISO/IEC 30107-3 certified PAD, Level 2 target** (certified passive SDKs are commodity as of 2025/26 — e.g. Identy.io L2 Oct 2025, ROC.ai, Regula); injection-attack detection (virtual camera/feed injection) on the roadmap | ISO/IEC 30107-3 |
| Key management | Per-deployment keys in KMS/HSM; keys never co-located with templates | + documented rotation and revocation drills, witnessed annually | — |
| Consent signalling | Honour the platform's suppression list (05 §4) | + capture-side consent signalling (no needless capture of opted-out faces) | PDPA |
| Data lifecycle | Template destruction on consent revocation with confirmation callback | + destruction attestation records retained for audit | PDPA |
| Assessment | Joint review against the pilot column at S2 (05 §8); certified-PAD budget decision by S2 (master plan open item 3) | Independent security assessment before national graduation; findings feed the full DPIA | — |

Failure to meet the Phase B column is a **graduation blocker**, not a negotiation point: the alternative is procuring a compliant service, since the integration is contract-shaped and replaceable by design (05 ADR F-1).

## 4. STRIDE threat model

Scope: the main assets and flows for Phase A; revisited at S6 and before each Phase B module activates (lab, imaging, and HHIMS connectors get their own STRIDE pass in 09). Format: threat → controls → residual.

| # | Asset / flow | STRIDE class | Threat scenario | Controls | Residual risk |
|---|---|---|---|---|---|
| T1 | Face match webhook (`/integrations/face/events`) | Spoofing, Tampering | Forged or replayed match event checks in an attacker-chosen patient (the prototype's actual state: endpoint was unauthenticated) | HMAC-SHA256 signature over timestamp + body, 300 s freshness window, key rotation via key-id, idempotency on `event_id`, per-station rate limit, mTLS where network permits, consent + policy gates before any effect (05 §3) | Low. Compromise of the shared secret requires face-service breach; rotation drill covers it |
| T2 | Staff tokens / sessions | Spoofing, Elevation of privilege | Stolen doctor token used to read records or sign prescriptions | Keycloak OIDC with short-lived access tokens (≤ 5 min) + rotating refresh tokens, MFA for staff, **step-up (fresh auth) for e-prescribing and break-glass** (02), token audience/scope validation at gateway, device-bound sessions where supported, immediate revocation path | Medium→Low. Step-up bounds the blast radius of a stolen access token to reads within its TTL — which are all audited and patient-visible (FR-5.8) |
| T3 | Agent prompt path | Tampering, Information disclosure | Prompt injection via record content (a note containing "ignore previous instructions…"), or via patient-authored text, steering the agent to exfiltrate or mis-propose | Retrieved record text fenced as data with instruction hierarchy; tool belts restricted per specialist; write path physically gated by Rx-safety topology + human sign-off interrupt (04 §2.1, §5); PII egress filter (no other patients' identifiers in output); injection probes in the CI eval set | Medium. Injection is an evolving class; mitigated by the fact that *no agent output becomes clinical record without clinician sign-off* and the agent cannot exceed the clinician's own FHIR access |
| T4 | FHIR API surface | Information disclosure, Elevation of privilege | Over-broad queries (e.g. unscoped `Patient?name=`) or IDOR-style resource access exposing other patients (the prototype's actual state: any doctor read all records) | HAPI is network-isolated, reachable only via gateway; authorisation interceptor enforces role + **doctor↔patient care relationship** + scope; consent interceptor enforces active `Consent`; search narrowing (compartment-based queries); `$everything` restricted to consented compartment; interceptor tests in CI including negative cases (03) | Low. Interceptors sit below every caller including the agent; the residual is interceptor defects — covered by mandatory negative tests and the S6 pen test |
| T5 | Audit trail | Tampering, Repudiation | Insider (DBA or compromised service account) deletes or edits `AuditEvent` rows to hide access | Append-only: audit writer role has INSERT only; hash-chained partitions with daily external anchoring (§6); nightly chain verification with alerting; audit review UI is read-only (FR-6.3) | Low. A privileged attacker could still halt *new* audit writes — mitigated by write-failure alerting (audit write failure = page) |
| T6 | Insider access (legitimate credentials, illegitimate purpose) | Information disclosure | Staff browse records of patients not under their care (VIP snooping — the classic health-data breach) | Care-relationship check at the interceptor (no relationship → no access, except break-glass); 100% read auditing; **patient-visible access log** (FR-5.8) as a deterrent; break-glass is loud, time-boxed, and reviewed (§8); anomaly review queries (volume per user, off-hours access) in the admin audit view | Medium. Detection-oriented by nature; the access-log transparency to patients is the strongest systemic deterrent |
| T7 | SSE / event stream (queue, face check-in events) | Information disclosure, Spoofing | Hijacked or unauthenticated event stream leaks check-in demographics; forged events poison the queue UI | SSE auth per 02 §11 (ADR I-10): the authenticated client exchanges its session for a **single-use, 30-second, opaque Redis ticket** redeemed via query param at stream open — log-scrubbed, bound to the issuing session, and worthless after redemption or expiry; **no bearer tokens ever appear in URLs**; events scoped per facility/role at notify-service; server is the only publisher (Redis pub/sub is internal network only); no PHI beyond queue-card minimum in event payloads; heartbeat + reconnect with re-auth (05 §5) | Low |
| T8 | Gateway / public edge | Denial of service | Volumetric or slow-request DoS takes down check-in and clinical access | Rate limiting per client/IP/route at Traefik, request-size and timeout limits, WAF posture (§5.6), autoscaled stateless services, and the care-never-blocked invariant: manual check-in and paper fallback procedures exist regardless (§8) | Medium at pilot (single site, low exposure); national edge gets dedicated DDoS protection (Phase B) |
| T9 | Secrets & supply chain | Elevation of privilege, Tampering | Leaked API keys (the prototype's actual state: live Anthropic key + Neon creds in a committed `.env`); malicious or vulnerable dependency/container | Vault-managed secrets, no secrets in repo or images, pre-commit + CI secret scanning, rotation schedule (§5.3); dependency and container scanning, SBOM, pinned digests (§5.5) | Low, given the controls run from S1 — see the standing lesson in §5.3 |

## 5. Controls catalogue

### 5.1 Encryption in transit

- **TLS 1.3** at the gateway (TLS 1.2 minimum floor for legacy clients, disabled ciphers list maintained); HSTS; certificates automated via ACME.
- Internal service-to-service traffic on an isolated container network; mTLS for the face-service webhook path where the network permits (05 §3) and for any cross-site link in Phase B.
- No plaintext listener anywhere, including dev-parity staging.

### 5.2 Encryption at rest & credential separation

- Encrypted volumes/managed-disk encryption for both PostgreSQL clusters (`hapi_db`, `app_db`), Redis persistence, and object storage (SSE-S3/KMS).
- **Per-service database credentials** with least privilege: core-api cannot touch HAPI's tables directly; the audit writer is INSERT-only (§6); agent-service has no direct DB grant on clinical data (it goes through core-api/FHIR).
- Backups encrypted with keys held in the vault/KMS, not on the backup host (10). Crypto-shredding is the destruction mechanism for backup media (§9).

### 5.3 Secrets management

- All secrets in a vault (SOPS/age for the pilot footprint or the cloud provider's secret manager — 10 owns the pick); injected at deploy time; **never in `.env` files in the repo, never in images, never in CI logs**.
- Secret scanning: pre-commit hooks + CI (gitleaks or equivalent) block pushes containing key material.
- **Standing lesson — the prototype leak:** the frozen backend repo contained a **live Anthropic API key and Neon database credentials in a plaintext `.env`**, and its face webhook was publicly unauthenticated. Week-0 actions (master plan §1, 12): **rotate the Anthropic key and Neon credentials immediately**, take the webhook off any public network, then freeze the repos. This incident is cited in security onboarding as the canonical example of why the vault rule is absolute.
- Rotation schedule:

| Secret | Rotation | Mechanism |
|---|---|---|
| Anthropic API key | 90 days + on incident | Vault re-issue; verified at agent-service startup (pinned-model check doubles as key check, 04 §4) |
| Database credentials (per service) | 90 days | Automated rotation job; dual-credential overlap |
| Face webhook HMAC secrets | 90 days | Dual-key rotation via `X-MedAgent-Key-Id` (05 §3) |
| Keycloak realm signing keys | 90 days | Keycloak key rotation (old key retained for token grace period) |
| TLS certificates | ≤ 90 days | ACME automation |
| S2S client credentials (face service, SMS) | 90 days | Vault + provider console |
| Break-glass and recovery credentials | 180 days + after every use | Manual ceremony, two-person rule, sealed storage |

This table is the authoritative rotation schedule; 10 §5 defers to it.

### 5.4 Rate limiting & input validation

- Gateway: per-IP and per-client-id token buckets; stricter buckets on auth endpoints (credential stuffing), the webhook (per station), and agent chat (per clinician — also a cost control, 04 §5).
- Application: every request body schema-validated (Pydantic; FastAPI rejects unknown/oversized payloads); FHIR resources validated against profiles at the store (03); file uploads type-sniffed, size-capped, stored in object storage with no execute path, and virus-scanned before any re-serving.
- Output encoding and CSP on the web apps (06); no HTML from record content is ever rendered unescaped (also an anti-injection measure for T3).

### 5.5 Supply chain

- **Dependencies:** lockfiles everywhere; `pip-audit`/`uv` audit + `npm audit` in CI (fail on high/critical); Renovate for routine updates; new-dependency review checklist (licence, maintenance, transitive weight).
- **Containers:** minimal base images, pinned by digest; Trivy scan in CI (fail on critical); images signed; SBOM (CycloneDX) generated per release and stored with the release artefact.
- **CI itself:** GitHub Actions with least-privilege tokens, pinned action SHAs, environment protection rules for staging/pilot deploys (10).

### 5.6 WAF posture

- **Phase A (pilot):** Traefik gateway hardening (rate limits, header sanitisation, request-size limits, method allowlists per route) + OWASP-CRS-equivalent rules via middleware/plugin where available; the small public surface (portal, gateway APIs, webhook) keeps this proportionate. Cloud-provider WAF/DDoS in front if pilot hosting is cloud.
- **Phase B (national):** dedicated WAF tier with managed OWASP CRS, bot management, and DDoS protection at the national edge; per-integration allowlisting (analyzer networks, HHIMS sites, NDHX) so machine interfaces are never on the open internet.

## 6. Audit trail tamper evidence (NFR-8, FR-6.3)

Every read and write emits a FHIR `AuditEvent` via the interceptor — it cannot be bypassed by any caller including the agent (01 §1). Tamper evidence on top:

- **Append-only storage:** `AuditEvent` rows live in monthly **append-only partitions**; the audit DB role has INSERT only (no UPDATE/DELETE); partition detach/archive is a scheduled, two-person operation.
- **Hash chaining:** each event carries `hash = SHA-256(prev_hash ‖ canonical_json(event))` computed at write time within its partition chain. Any retro-edit or deletion breaks every subsequent hash.
- **Periodic anchoring:** a daily job signs the chain head (per partition) and writes the digest to **object storage with object-lock (WORM)**, separate credentials, separate failure domain. Phase B adds RFC 3161 trusted timestamping (or an equivalent national anchor agreed with the MoH governance body) so even platform operators cannot rewrite history undetected.
- **Verification:** a nightly job re-walks recent chains and compares anchors; mismatch = page-level alert + incident. Audit **write failure is also a page**: services treat "cannot audit" as an availability event, and the S6 test evidence includes a deliberate audit-write-failure drill.
- **Review:** admin audit UI (FR-6.3) is strictly read-only, itself audited, and includes canned insider-threat queries (per-user volume, off-hours, no-relationship access attempts, break-glass log).
- **Patient transparency:** the portal access log (FR-5.8) is a filtered projection of the same events — one source of truth.

## 7. AI governance (spec §4.4)

The technical design is in 04; this section states the governance controls and regulatory posture, which the compliance pack references.

1. **Human-in-the-loop, structurally.** No AI-generated clinical entry reaches the record without clinician e-sign-off — enforced by graph topology (the LangGraph interrupt is the only path to commit; 04 §2.1) and step-up auth for prescriptions. The clinician is the decision-maker of record for every entry; the platform can evidence this per entry (proposal, safety verdict, signer, timestamp, audit).
2. **Citation traceability.** Every factual answer cites the record entry it came from; the citation validator refuses uncited claims; general-knowledge content is explicitly marked and never used for patient-specific facts (04 §2.3). This is the anti-fabrication control demanded by FR-3.4.
3. **Versioned models and prompts.** Model IDs are pinned in config and verified at startup; prompts are versioned files changed only by PR; **models never self-update in production**; rollback is a config revert (04 §4, §6).
4. **Eval gate in CI.** The golden clinical set (≥150 cases at S3, growing) runs on every change to prompts, tools, graph, model pin, or the DDI dataset. Hard gates: Rx-safety fixtures 100%, citation faithfulness ≥ 98%; regressions block merge exactly like failing tests (04 §6).
5. **Drift and bias monitoring.** Sampled live-traffic tracing with dashboards: refusal rate, citation coverage, tool-error rate, clinician edit-distance on proposals; **bias axes monitored explicitly** — performance across Sinhala/Tamil/English name handling, age bands, and sex, with eval-set stratification so degradation on any stratum is visible, not averaged away. Alert thresholds reviewed monthly with the clinical lead.
6. **Incident response for AI errors.** A clinically significant AI error (wrong citation acted on, unsafe proposal that passed screening, missed interaction) is a **security-grade incident**: incident record, clinical review, root-cause assigned to the guardrail layer that should have caught it, a new eval case added before closure, and — where a patient could have been affected — controller notification per the breach runbook. The AI incident register is part of post-market monitoring evidence.
7. **Governed learning loop.** Clinician accept/edit/reject feedback becomes eval cases first; model/prompt changes ship only through the gate; datasets are curated, versioned, and reviewable (04 §6). Nothing learns silently.

### 7.5 Medical-device / CDS regulatory posture

The AI layer is positioned as **clinical decision support with a qualified professional in the loop**, not an autonomous diagnostic device: it retrieves, summarises with citations, drafts proposals, and screens prescriptions deterministically; a clinician signs every entry. Under IMDRF SaMD risk framing this is the lower-risk "inform/drive clinical management with clinician verification" category. Sri Lanka's **NMRA** medical-device regime does not currently impose a specific SaMD pre-market pathway for this class, but the posture is defensive: maintain the technical documentation a device file would need (intended use statement, architecture, eval evidence, post-market monitoring = drift dashboards + AI incident register, change control = the eval gate), so that if NMRA or the MoH governance body issues CDS guidance mid-programme, the platform can conform by assembling existing artefacts rather than re-engineering. The MoH-led governance body owns AI model approvals for national rollout (spec §6.2). Reviewed each phase gate.

## 8. Break-glass and the care-never-blocked invariant

The spec's boxed invariant — *care is never blocked* — is a design constraint on every control in this document. Controls fail toward manual, audited paths, never toward "no treatment":

- **Break-glass access (spec §4.2):** a clinician without a care relationship (or where consent is withheld) can invoke emergency override for a named patient. Mechanics: step-up authentication, mandatory structured reason, access elevated for a bounded window (**default 60 min, hard ceiling 4 h**, per 02 §6.1), **loud** — the session is visually marked, an alert goes to the facility admin in real time, every action is audited with the break-glass flag, and the access appears in the patient's access log (FR-5.8). Post-hoc review within 72 h by the admin with DPO visibility; unjustified use is a disciplinary/PDPA matter. Break-glass never bypasses the Rx-safety gate or e-sign-off — it bypasses *relationship/consent gating only*. Phasing per 02 §6.1: the automated break-glass workflow activates in **Phase B**; the Phase A pilot runs an **audited manual-override procedure** (admin-granted, time-boxed, AuditEvent-logged, post-reviewed) with the same invariants — care is never blocked in either phase.
- **Identity fallback:** face recognition below threshold, liveness fail, opt-out, or face-service outage all route to manual check-in (05 §3); recognition is an accelerator, never a gatekeeper.
- **Degradation:** AI unavailable → the workspace functions fully on structured views (04 §7); notify-service down → UI polls; network-degraded rural operation is Phase B offline-first (PowerSync) with Phase A graceful degradation (01 §5).
- **Consent withheld** never blocks treatment — it blocks *platform data flows* (face events dropped, portal sharing off); the clinician treats via manual identity and break-glass where clinically necessary, all audited.

## 9. Retention & destruction policy per record class

Defaults below are proposals for controller sign-off (the hospital/MoH owns clinical retention policy); the DPIA records the agreed values. Principle: clinical data is a lifetime asset by national design; everything operational is minimised.

| Record class | Store | Retention (default) | Destruction |
|---|---|---|---|
| Clinical record (all FHIR clinical resources) | `hapi_db` | **Lifetime of the patient** (the product premise) + post-mortem statutory period per MoH policy; version history retained | Deletion only via governance decision; erasure requests answered per §2 (qualified) |
| Consent records + full history | FHIR `Consent` | Lifetime + 6 years after last revocation (demonstrability) | With clinical record |
| AuditEvent | Audit partitions + WORM anchors | **7 years minimum** (2 years hot, remainder in sealed archived partitions) | Partition crypto-shred after expiry, logged |
| Chat transcripts (LangGraph checkpointer) | `app_db` | **90 days rolling**, then purged — clinical outcomes are already FHIR resources (01 ADR A-4); transcripts are operational | Automated purge job; purge itself audited |
| Clinician feedback / eval-derived cases | eval repo | Indefinite, **de-identified before entering the dataset** (04 §6) | n/a after de-identification |
| `FaceCheckinEvent` log | `app_db` | 2 years (aligned with 05 §7) | Automated purge |
| Queue / check-in operational state | `app_db` + Redis | Days (Redis TTL) / 90 days (rows) | TTL / purge |
| Notification logs (SMS/push send records) | notify-service store | 1 year; message bodies carry minimal PHI by policy (09 §12) | Automated purge |
| Application logs, traces, metrics | Grafana stack | 30–90 days; PII scrubbed at emission (no identifiers in logs by lint rule) | Rolling deletion |
| Backups | Encrypted object storage | 35 days point-in-time + 12 monthly fulls | **Crypto-shredding** (key destruction) at expiry — the practical destruction mechanism for backup media |
| `ext_face_id` linkage | MPI | Until consent revoked / re-enrolment (05 §7) | Cleared on revocation; face-service template destruction confirmed by callback |
| Biometric templates / images | **Not held** — face service | Contractual: templates until revocation; raw images not retained post-enrolment (§3.2) | Destruction attestation from the service |

Destruction is evidenced: purge jobs log counts and ranges; manual destructions produce signed records; the DPO holds the destruction register.

## 10. DPIA and the S6 compliance pack

### 10.1 DPIA outline (DPIA-lite at S6; full DPIA before Phase B)

1. **Systematic description** — purposes, data categories (health, biometric-adjacent linkage, identifiers), flows (01 §4), recipients (face service, Anthropic, SMS aggregator), storage and locations, retention (§9).
2. **Necessity & proportionality** — lawful bases per purpose (§2), minimisation evidence (biometric isolation, PHI-minimised prompts, `app_db` kept deliberately small), consent design, transparency (privacy notices Si/Ta/En).
3. **Risks to data subjects** — from the STRIDE model (§4) re-expressed as harms (exposure, discrimination, wrong-patient treatment, chilling effects of biometrics), likelihood × severity scored.
4. **Mitigations** — controls catalogue mapping, residual-risk acceptance by the controller.
5. **Consultation** — DPO opinion; clinician and patient-representative input from pilot co-design; Authority consultation if high residual risk remains.
6. **Sign-off & review** — controller sign-off pre-go-live; review at each phase gate and on material change (new integration, new model class, new data category).

### 10.2 S6 compliance pack contents (go-live gate)

| Artefact | Source |
|---|---|
| DPIA-lite (signed) | §10.1 |
| Threat model + controls mapping | §4, §5 |
| Consent records export (sample + mechanism demo) | §2, 03 |
| Audit coverage report (100% read/write evidence + chain verification run) | §6 |
| Pen-test report | Scope: gateway/edge, webhook forgery attempts, authz bypass (doctor↔patient), consent bypass, IDOR on FHIR surface, prompt-injection probes, SSE auth; external tester; criticals fixed before go-live |
| RBAC & access review | 02 |
| Restore-drill and audit-write-failure drill evidence | 10 |
| Breach runbook + incident/AI-incident register (empty but exercised) | §2, §7 |
| ROPA + processor agreements + transfer assessments | §1, §2 |
| Face-service pilot-column assessment | §3.2, 05 §8 |
| Vulnerability disclosure policy (published) | §11 |

## 11. Vulnerability disclosure & patch SLAs

- **Disclosure channel:** published `security.txt` + security contact on the portal; safe-harbour statement for good-faith research; acknowledgement within **48 hours**, triage within 5 working days; coordinated disclosure default 90 days. Reports touching patient data are simultaneously assessed under the breach runbook.
- **Patch SLAs (from vulnerability confirmation or advisory publication):**

| Severity (CVSS-informed) | Exposed/edge components | Internal components |
|---|---|---|
| Critical (exploitable, PHI-relevant) | 48 hours (emergency change) | 7 days |
| High | 7 days | 14 days |
| Medium | 30 days | 30 days |
| Low | Next scheduled release (≤ 90 days) | ≤ 90 days |

- Emergency changes still pass CI (including the eval gate if agent-adjacent) but may use an expedited review; the change record notes the SLA clock.
- Base-image and dependency refresh cadence: monthly, forced by Renovate + CI scans (§5.5), so patch SLAs start from a current baseline.

## 12. Decisions

| ADR | Decision | Rationale | Rejected |
|---|---|---|---|
| SEC-1 | Audit tamper evidence = hash-chained append-only partitions + daily WORM anchoring (+ RFC 3161 in Phase B) | Meets "tamper-evident" (NFR-8) with boring, verifiable cryptography; verification is a nightly job anyone can re-run; proportionate to a 2-dev pilot and scales nationally | Blockchain/DLT anchoring (complexity theatre for this need); WORM-only without chaining (detects nothing about ordering/omission); trusting DB permissions alone |
| SEC-2 | Secrets in SOPS/age vault for the pilot footprint, or cloud secret manager if pilot hosting is cloud; decision finalised in 10 — the invariant is *no secrets in repo/images/env-files*, whichever backend | The invariant matters more than the backend; SOPS/age fits compose-based deploys; cloud manager fits managed hosting; both support the §5.3 rotation schedule | HashiCorp Vault server day 1 (operational weight for 2 devs); committed `.env` (the prototype's proven failure mode) |
| SEC-3 | Anthropic API with enterprise no-training terms + PHI-minimised prompts + documented transfer assessment; Phase B review of regional/sovereign hosting options if the Authority's cross-border rules require it | Model quality is a clinical-safety input; minimisation + contract + assessment is a defensible PDPA posture today; the review trigger is written down so enforcement changes mid-pilot don't cause improvisation | Self-hosted open-weights LLM now (materially weaker clinical reasoning = a different, larger safety risk; revisit as sovereign options mature); blocking all cross-border processing (kills the AI layer, the product's core) |
| SEC-4 | CDS posture: clinician-in-the-loop decision support with device-grade documentation maintained, no pre-market claim | Matches the actual system behaviour (nothing autonomous reaches the record); keeps the programme ready for NMRA/MoH CDS guidance without re-engineering | Claiming SaMD certification now (no applicable local pathway, high cost, no requirement); ignoring device framing entirely (fragile if guidance lands mid-rollout) |
| SEC-5 | Breach notification working target 72 h to the Authority, tightened/adjusted when the Authority's rules fix the period | GDPR-parity assumption is the safe planning bound while subsidiary rules settle post-Act 22/2025 | Waiting for the rules before writing the runbook |
| SEC-6 | Break-glass bypasses relationship/consent gates only — never Rx-safety or sign-off — and is loud, time-boxed, and patient-visible | Preserves both invariants at once: care is never blocked *and* prescriptions are always screened and signed; transparency deters misuse (T6) | Full-bypass break-glass (unsafe); no break-glass (blocks emergency care — violates the spec invariant) |
| SEC-7 | Retention defaults per §9 proposed by the platform, signed by the controller in the DPIA | Clinical retention is the controller's legal call; the platform must still ship enforceable defaults and purge automation | Hard-coding retention unilaterally; indefinite retention of operational data "just in case" |
