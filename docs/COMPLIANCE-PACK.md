# Compliance pack (S6 — pilot readiness)

Assembly of the compliance artifacts for the supervised single-facility pilot.
This is an **index + DPIA-lite**; the detailed design rationale lives in
[solution/08-security-privacy-compliance.md](solution/08-security-privacy-compliance.md).
Governing law: Sri Lanka PDPA (and the Data Protection Authority's rules as they
are issued); clinical governance per the pilot hospital's ethics approval.

## 1. Artifact index

| Artifact | Covers | Status |
|----------|--------|--------|
| [SECURITY-REVIEW.md](SECURITY-REVIEW.md) | As-built security posture, findings, accepted-risk register | Current (2026-07-23) |
| [THREAT-MODEL.md](THREAT-MODEL.md) | STRIDE against the architecture, ranked residual risks | Current |
| [RUNBOOKS.md](RUNBOOKS.md) | Backup/restore (drill verified), degradation responses | Current |
| [solution/08-…](solution/08-security-privacy-compliance.md) | Design-time privacy/compliance controls, ADRs | Design |
| [solution/02-…](solution/02-identity-access-mpi.md) | Identity, RBAC, care-relationship authz, MPI | Design |
| CI (`.github/workflows/ci.yml`) | Lint, type, test, **dep-audit gates** (pnpm + pip-audit) | Active |

## 2. DPIA-lite

### 2.1 Personal / special-category data processed
- **Identifiers:** name, PHN (national), NIC, phone, DOB, sex, address (GN).
- **Special category (health):** conditions, medications, allergies, vitals,
  labs, immunisations, encounters, clinical notes, prescriptions.
- **Biometric:** face templates — held **only** by the external face service
  (encrypted, no raw image retention, ISO/IEC 24745 direction, 05 §7); the
  platform stores only an opaque `ext_face_id` link, never templates or images.

### 2.2 Lawful basis & purpose
- Provision of medical care at the pilot facility (clinical care is the purpose).
- Consent controls: face-recognition check-in is **opt-in** and revocable from
  the portal (immediate effect via cache invalidation); a **non-biometric
  manual check-in path always exists** (no one is forced into biometrics).

### 2.3 Data flows & minimisation
- Clinical data stays in FHIR (`hapi_db`); reads are scoped to the patient
  compartment; only a care-related clinician (grant) or the patient (self) can
  read a record.
- **Cross-border:** clinical prompt content is sent to the Anthropic API (USA),
  **PHI-minimised** (only clinically necessary fields; no gratuitous
  identifiers), under enterprise no-training terms (ADR SEC-3). SMS via local
  aggregators carries **no** cross-border PHI. Regional-hosting review is a
  Phase B trigger if the Authority's rules require it.
- Logs and audit payloads carry **opaque IDs only** (verified).

### 2.4 Retention & deletion
- Clinical records: retained per health-records policy (not user-deletable —
  medico-legal). PDPA erasure requests are handled as restriction/annotation
  where clinical-record law overrides deletion, documented per request.
- Redis (sessions, caches, SSE tickets): ephemeral, TTL-bound, not a record.

### 2.5 Data-subject rights
- **Access:** portal shows the patient their own record + a plain-language
  **access log** ("who viewed/changed your record") — FR-5.8.
- **Portability:** self-service export — human-readable summary **and** full
  FHIR JSON bundle (`$everything`) — FR-5.6/6.4; each export is audited.
- **Consent:** view/toggle from the portal; changes take effect immediately and
  are audited.
- **Rectification/complaint:** via the facility's data-protection contact
  (manual workflow in Phase A).

### 2.6 Security measures (summary — full detail in SECURITY-REVIEW.md)
OIDC auth + BFF token isolation; care-relationship + self-compartment authz;
TLS in transit; HAPI not externally reachable; transactional audit trail;
gateway rate limits; dependency-audit CI gates; secret hygiene verified.

## 3. Pilot go / no-go checklist (10 §8 exit criteria)

- [x] Security review complete, risks accepted in writing (this pack)
- [x] Dependency audit clean + gated in CI
- [x] Backup + restore drill verified within a maintenance window
- [x] Deterministic Rx-safety eval gate 100% (23/23)
- [x] Degradation runbooks documented
- [x] NFR-2 (record load p95 < 2 s) evidenced at 3× pilot concurrency
- [ ] **R-1**: FHIR-boundary enforcement + audit hash-chaining (defence-in-depth;
      accepted for supervised single-facility pilot, required before multi-facility)
- [ ] **R-3**: LLM concurrency/soak evidence (recorded-LLM harness)
- [ ] Pilot staff trained; on-call-lite rota active; first consented patients
- [ ] DPIA reviewed & signed by the facility DPO / ethics board

## 4. Sign-off

| Role | Name | Date | Decision |
|------|------|------|----------|
| Clinical lead | | | |
| Data protection officer | | | |
| Engineering lead | | | |

*Pack assembled 2026-07-23. Re-review before go-live and on any change to data
flows, cross-border processing, or the residual-risk register.*
