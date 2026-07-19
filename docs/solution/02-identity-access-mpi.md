# 02 · Identity, Access & Master Patient Index

Version 1.0 · July 2026 · MedAgent Platform
Status: Draft for review

## Executive summary

Identity and access are delivered by **Keycloak 26.x** (OAuth2/OIDC, realm-as-code) fronting every human and service principal, with a **core-api master patient index (MPI)** owning PHN issuance, demographic deduplication, and the reserved SLUDI linkage. Authorisation is two-layered: Keycloak answers *who you are and what role you hold*; the platform's **care-relationship model** answers *whether you may see this patient right now* — closing the prototype flaw in which any doctor could read every record. Staff authenticate with MFA; e-prescribing and break-glass require **step-up authentication** enforced through Keycloak ACR/LoA flows; break-glass access is time-boxed, reason-captured, and lands in a mandatory post-review queue. Guardian proxy access is explicit, time-bound, and expires automatically at majority (FR-5.9). All roles for every spec actor are defined in the realm from day 1; only the Phase A subset is activated at the pilot.

## FR traceability

| Requirement | Section |
|---|---|
| FR-1.7 record loads only for confirmed, authorised identity | §7 (queue-based grant) |
| FR-2.4 manual patient search (name / PHN / phone) | §8.3 |
| FR-4.8 clinician confirmation before commit (auth dimension) | §5.2 (step-up for Rx sign-off) |
| FR-5.2 consent control over who may view records | §7 (relationship grants), 03 (consent interceptor) |
| FR-5.7 emergency profile for authorised emergency staff | §6 (break-glass, emergency-profile carve-out) |
| FR-5.8 patient access log | §7.5, 03 §5.3 |
| FR-5.9 / FR-7.8 guardian proxy, expiry at majority, both parents | §9 |
| FR-6.1 staff accounts, roles, departments | §10.1 |
| FR-6.2 threshold & safety-rule configuration | §10.2 |
| FR-6.3 log / audit review | §10.3, §6.4 |
| FR-6.4 consent records & data-subject requests | §10.4, 03 §8 |
| FR-7.1 lifetime profile at birth with PHN | §8.2 |
| FR-7.2 SLUDI linkage, adapter reserved | §8.5 |
| Spec §4.2 RBAC, MFA + step-up, break-glass, guardian access | §4, §5, §6, §9 |

## 1. Keycloak deployment

- **Version:** Keycloak 26.x (26.7 current at time of writing), official container image, custom image layer only for theme + health probes. Runs in `platform/keycloak`, network-reachable only via the gateway (`/auth` route) — admin console bound to an internal hostname, never exposed publicly.
- **Database:** dedicated `keycloak` database in the platform PostgreSQL cluster with its own credentials (NFR-10; per-service DB credentials per 01 §5).
- **Realm-as-code:** the entire realm — clients, roles, client scopes, authentication flows, required actions, ACR/LoA mapping — is declared in versioned JSON and applied idempotently by **keycloak-config-cli** as a CI/CD step (`infra/ci`, see 10). No hand-edits in the admin console persist: drift is overwritten on the next deploy. Secrets (client secrets, SMTP credentials) are injected at apply-time from the vault, never stored in the JSON.
- **Topology:** single instance for dev; 2 replicas behind the gateway for pilot (Keycloak 26 uses persistent user sessions in the database by default, so failover does not log users out). HA cache via the default `ispn` stack on the internal network.
- **Hygiene:** `master` realm holds no application users; a bootstrap admin exists only for keycloak-config-cli's service account; brute-force detection enabled realm-wide (supersedes the prototype's hand-rolled lockout logic, per 00 §1).

## 2. Realm and client design

One application realm, `medagent`. (A second realm is *not* used to separate staff from patients — cross-realm token exchange complicates guardianship and adds no isolation the RBAC model doesn't already provide; see ADR I-2.)

| Client | Type | Flow | Notes |
|---|---|---|---|
| `web` | **Confidential** | Authorization Code + **PKCE (S256 enforced)** | Single client for doctor workspace, patient portal, and kiosk route group (one Next.js app, 01 §2). Client secret held server-side by the Next.js BFF (06 §2) — the browser never holds tokens; httpOnly session cookies carry the session and the BFF exchanges/refreshes tokens server-side. No implicit/hybrid flow, exact redirect URIs only, `web` origins pinned. |
| `kiosk-device` | Confidential | Client credentials (station-scoped service account) | One credential per physical kiosk station (06 §2.2), rotated on the secrets schedule (08). Minimal scopes: check-in queue read/write only — no clinical scopes, no user impersonation. |
| `core-api` | Confidential (bearer-only usage) | — | Resource server; validates access tokens, audience `core-api`. Its service account (client credentials) is used for Keycloak Admin API calls (§10.1). |
| `agent-service` | Confidential | Client credentials (S2S) | Resource server for chat requests **and** service client when calling core-api / FHIR on its own behalf (scheduled reminder jobs). Interactive agent calls always carry the *clinician's* token forward — the service account is never used to widen a user's access. |
| `notify-service` | Confidential (bearer-only usage) | — | Validates SSE ticket-issuing requests (§11); no user-facing login. |
| `fhir-gateway` | Confidential (bearer-only usage) | — | Logical audience for direct FHIR-path requests validated by the HAPI authz interceptor (03 §5.1). |
| `keycloak-config-cli` | Confidential | Client credentials | CI-only; realm administration scope; secret held in CI vault. |

**Explicitly not a Keycloak client: the face-recognition service.** Its inbound webhook is authenticated by HMAC-SHA256 signature + timestamp + key rotation, and outbound calls to it use the S2S credentials agreed in its API contract — see 05 §3 and ADR F-2 there. Keeping the external service out of the realm keeps the trust boundary explicit and the integration contract-only (locked decision D5).

**Scopes.** Pilot uses plain OAuth2 scopes (locked decision D8; SMART on FHIR v2 scope grammar is a post-pilot mapping exercise). Default + optional client scopes:

| Scope | Meaning | Granted to |
|---|---|---|
| `clinical.read` | read clinical FHIR resources (subject to §7 relationship + consent checks) | doctor, nurse, midwife_phm, lab_tech, radiologist |
| `clinical.write` | propose/commit clinical writes (subject to sign-off, 04) | doctor, nurse (vitals), midwife_phm (Phase B) |
| `rx.sign` | commit MedicationRequest — requires `acr=loa2` (§5.2) | doctor |
| `queue.manage` | check-in, manual identity fallback, queue ordering | receptionist, nurse |
| `patient.self` | patient/guardian compartment access to own (or ward's) record | patient, guardian |
| `admin.iam`, `admin.config`, `admin.audit`, `admin.consent` | FR-6.1–6.4 split so audit review ≠ user management | admin (composite) |
| `analytics.national` | de-identified/aggregate dashboards only — never row-level PHI | moh_planner (Phase B) |

Audience is enforced **per service**: each resource server gets a dedicated audience client scope (`aud:core-api`, `aud:agent-service`, `aud:notify-service`, `aud:fhir-gateway`) carrying a hardcoded-audience protocol mapper. The web client requests only the audiences it needs per call path; every service rejects tokens whose `aud` does not include itself. A token minted for chat cannot be replayed against the FHIR path unless that audience was requested and granted.

## 3. RBAC role matrix (all spec actors)

Realm roles, one per spec §1.3 actor, all **defined in the realm JSON from day 1**; the Phase A column marks which are activated (assignable) at the pilot. Composite roles bundle the scopes above. Facility and department are **token claims sourced from PractitionerRole**, not roles — the same doctor role works at any facility, and the authz interceptor scopes by facility claim (03 §5.1).

| Role | Core permissions (scopes) | Record visibility rule (§7) | Phase A |
|---|---|---|---|
| `doctor` | clinical.read, clinical.write, rx.sign | Care relationship required (encounter / queue / appointment / referral); break-glass eligible | **Active** |
| `nurse` | clinical.read (summary-level), clinical.write (vitals only — FR-4.5) | Same-facility care relationship; no Rx | **Active** |
| `receptionist` | queue.manage, MPI demographic search (no clinical payload) | Demographics + appointment data only — never clinical resources | **Active** |
| `midwife_phm` | clinical.read (child-health subset), clinical.write (growth, immunisation — FR-7.3/7.4) | Assigned PHM area cohort (Phase B field app, 09) | Defined, dormant |
| `lab_tech` | lab order/specimen/result workflow (FR-8.x) | Order-scoped: only patients with an active ServiceRequest routed to their lab | Defined, dormant |
| `radiologist` | imaging worklist, report authoring (FR-9.3/9.4) | Study-scoped: only patients on their worklist | Defined, dormant |
| `admin` | admin.iam, admin.config, admin.audit, admin.consent | **No clinical record access** — administration is not care | **Active** |
| `patient` | patient.self | Own compartment only | **Active** |
| `guardian` | patient.self (proxied; Phase A read-only, §9) | Linked ward's compartment, within grant window (§9) | **Active** (read-only) |
| `moh_planner` | analytics.national | Aggregate/de-identified only (FR-14.4, FR-11.3) | Defined, dormant |
| `break_glass` (modifier) | temporary relationship override (§6) | Time-boxed grant, flagged audit | Model designed; **Phase A: audited manual procedure** (§6), automated workflow Phase B |

Least-privilege checks in CI: a realm-lint step asserts no role accumulates scopes outside this matrix (guards against console drift even though config-cli overwrites it).

## 4. MFA for staff

- All staff roles require **TOTP** as a Keycloak required action at first login; WebAuthn/passkeys enabled as a preferred second factor where hardware allows (FIDO2 aligns with spec §5.1 identity row). Patients: password + OTP-on-new-device (SMS) — mandatory MFA for patients would suppress portal adoption; revisit Phase B with SLUDI authentication (§8.5).
- Conditional-OTP is bound in the browser flow to the staff roles, not globally, so kiosk/patient flows are untouched.
- Recovery: admin-initiated re-enrolment only (FR-6.1); no self-service email reset for staff accounts (pilot hospital staff verified in person).
- **Session lifetimes:** staff SSO sessions are capped at **12 h maximum** with a **30 min idle timeout** (realm session settings — a ward workstation left logged in does not stay live overnight, and step-up freshness in §5 is independent of session age). Patient portal sessions may be longer-lived per portal UX (07), with OTP-on-new-device as the compensating control.

## 5. Step-up authentication (ACR/LoA)

### 5.1 Mechanism

Keycloak's native step-up support maps **ACR values to Levels of Authentication** in the realm's browser flow:

- Realm ACR-to-LoA map: `loa1 → 1` (password or SSO cookie), `loa2 → 2` (password/passkey **+ OTP, freshly presented**).
- The browser authentication flow has conditional subflows keyed on requested LoA; LoA 2 condition sets **Max Age = 300 s**, so a step-up assertion is only valid if the second factor was presented within the last five minutes — a stale morning login cannot satisfy an afternoon step-up.
- A client requests step-up with `claims={"id_token":{"acr":{"essential":true,"values":["loa2"]}}}` (or `acr_values=loa2`) on a re-authorisation redirect; Keycloak runs only the missing factor, and the new token carries `acr: loa2`.

### 5.2 Enforcement points

| Action | Required ACR | Enforced by |
|---|---|---|
| Normal login, read, notes, vitals | `loa1` | gateway token validation |
| **e-prescription sign-off** (FR-4.8 for MedicationRequest) | `loa2`, ≤ 300 s old | agent-service `POST /agent/resume` rejects a `signed` Rx resolution whose token lacks fresh `loa2` (04 §2.1); core-api commit path re-checks — two layers, fail-closed |
| **Break-glass activation** | `loa2`, ≤ 300 s old | core-api `POST /authz/break-glass` (§6) |
| Consent revocation on behalf of ward | `loa2` | core-api consent write path |
| Admin: role changes, threshold changes | `loa2` | core-api admin endpoints (§10) |

UX: the sign-off card triggers a silent redirect (`prompt=none` fails → OTP prompt) so step-up costs one OTP entry, not a full re-login. The `acr` claim is verified from the **access token** server-side; the UI's belief is never trusted.

## 6. Break-glass emergency access

Break-glass exists so that *care is never blocked* (spec §4.4 box) when no care relationship or consent exists — the unconscious arrival, the emergency transfer. It is deliberately implemented **in core-api, not as a Keycloak role grant**: mutating realm roles at 3 a.m. is slow, hard to time-box, and pollutes the identity layer with operational state.

**Phasing.** The model below is fully designed now; the Phase A pilot operates it as an **audited manual-override procedure**: an admin grants the time-boxed override at the requesting doctor's step-up-authenticated request, with the same reason capture and the same default 60 min / hard ceiling 4 h; every access under it is written to `AuditEvent` with `purposeOfUse = BTG`; post-review runs as a queue in the admin UI (on paper if the UI lags the pilot start). The **automated** break-glass workflow — the `break_glass_grants` table with self-service invocation and the automated review queue — **activates in Phase B** (sprint plan, 11). FR-5.7's Phase A mechanism is the pre-break-glass minimal emergency view (§6.2), which requires no override at all.

### 6.1 Flow (target design; self-service invocation activates Phase B)

1. Doctor (role with break-glass eligibility) opens the patient by PHN/search and selects *Emergency access*.
2. Step-up auth (`loa2`, §5.2) — the override itself must be strongly authenticated.
3. Mandatory structured reason (picklist: unconscious/unable to consent, life-threatening emergency, mass-casualty; plus free text ≥ 20 chars).
4. core-api writes a `break_glass_grants` row (`app_db`): practitioner, patient, facility, reason, `expires_at = now() + 60 min` (configurable per FR-6.2, hard ceiling 4 h), and publishes an authz-cache invalidation (§7.4).
5. The HAPI authz interceptor honours the grant as a valid relationship; the consent interceptor is **overridden for treatment purpose only** — every access under the grant is written as `AuditEvent` with `purposeOfUse = BTG` (HL7 break-the-glass code) and linked to the grant ID (03 §5.3).
6. Expiry is automatic (grant row TTL checked in the decision path; no revocation job needed to *stop* access). Early manual release available.

### 6.2 Guardrails

- **Time-boxed:** default 60 min, non-renewable without a fresh step-up + reason.
- **Scope-limited:** read + emergency-relevant writes; Rx still requires `rx.sign` + step-up as normal. FR-5.7's emergency profile (allergies, blood group) is additionally exposed as a *pre-break-glass* minimal view so full override is often unnecessary — this minimal view is the **Phase A delivery mechanism for FR-5.7**, available to authorised emergency staff without invoking any override.
- **Post-review queue (mandatory):** every grant creates a review task for the admin/audit role (FR-6.3). Reviews record justified / not-justified / escalate; unreviewed grants older than 72 h page the DPO contact (08). Patients see break-glass access in their access log (FR-5.8) — no silent overrides.
- **Rate anomaly detection:** > N grants per practitioner per week alerts (threshold configurable, FR-6.2).

## 7. Care-relationship authorisation (fixing the prototype flaw)

The prototype allowed any authenticated doctor to read any patient. The corrected model: **a staff token alone never grants access to a specific patient's record** — there must be an active *relationship grant*. Keycloak stays out of this (relationships change by the minute; tokens live for minutes and must not encode patient lists).

### 7.1 Grant sources (evaluated in precedence order)

| Grant | Created by | Window | Spec hook |
|---|---|---|---|
| **Encounter-based** | Practitioner is `Encounter.participant` on an in-progress encounter | encounter start → close **+ 72 h** documentation tail | FR-4.x write-back happens here |
| **Queue-based** | Patient checked in (face or manual) to a clinic session the doctor/nurse is staffing | check-in → end of clinic day | FR-1.7: check-in *is* the authorisation event that loads the record |
| **Appointment-based** | Booked appointment with the practitioner | −24 h → +7 days around the slot | FR-2.3 pre-reading, follow-up |
| **Referral-based** | Active referral (Phase B: `ServiceRequest`+`Task`) to receiving unit/practitioner | referral acceptance → closure | FR-10.2 consent-gated receiving-end access |
| **Order-based** | Active lab/imaging order routed to the tech/radiologist's unit (Phase B) | order → result release | FR-8.x, FR-9.x worklists |
| **Guardian link** | §9 proxy relationship | until expiry/majority | FR-5.9 |
| **Break-glass** | §6 | grant TTL | spec §4.2 |

Phase A implements encounter-, queue-, and appointment-based grants plus guardian (read-only, §9) and break-glass (admin-granted manual procedure, §6); referral/order grants land with their Phase B modules. Longitudinal `CareTeam` membership (chronic-care panels) is a Phase B addition on the same evaluation path.

### 7.2 Decision service

core-api exposes an internal endpoint `GET /internal/authz/decision?actor=…&patient=…&action=read|write` that resolves the grant tables + `app_db` queue state and returns `permit | deny (+reason)`. Callers:

- the **HAPI authz interceptor** on every FHIR request in staff context (03 §5.1);
- core-api's own BFF endpoints;
- agent-service before tool execution (tools are per-patient scoped — salvaged prototype pattern, 04).

### 7.3 Caching

Decisions cache in Redis (`authz:{actor}:{patient}` → verdict, **TTL 60 s**). 60 s bounds the staleness of a *revocation*; grants appearing (check-in) publish an eager invalidation so access is immediate, not delayed by TTL.

### 7.4 Invalidation events

Published on Redis (`authz.invalidate` channel) by core-api on: check-in / queue removal, encounter close, appointment cancellation, guardian link change, break-glass grant/expiry/release, consent change (consent cache shares the mechanism, 03 §5.2).

### 7.5 Patient-visible access log

Because every permitted access produces an `AuditEvent` naming the actor and the grant type (03 §5.3), FR-5.8's access log is a filtered audit query in the patient portal — including break-glass entries. Denied attempts by staff are also audited (security signal, FR-6.3).

## 8. Master Patient Index (core-api)

The MPI lives in core-api's `app_db` (01 §3): it owns PHN issuance, demographic search, dedup, guardian links, `ext_face_id` linkage (05), and the SLUDI binding. It **projects** to the FHIR `Patient` resource (system of record for clinical demographics) — MPI rows carry identity/linkage state, never clinical data (ADR A-5 in 01).

### 8.1 PHN format

- **11 digits: 10 significant + 1 check digit (Verhoeff).** Verhoeff over mod-11 because it catches all single-digit errors *and* all adjacent transpositions in a digits-only alphabet — PHNs will be read over phones and typed at kiosks. No embedded semantics (no DOB, no facility prefix): meaningful digits leak data and break when people move.
- Issued from a per-facility allocated block (offline-safe issuance at rural sites, Phase B) with central reconciliation; collisions impossible by construction.
- Rendered grouped `XXX XXX XXX XX` for humans; stored canonical 11-digit.
- **Alignment caveat:** the Ministry of Health has an existing PHN concept in HHIMS deployments. Before pilot go-live the format is to be confirmed against the MoH/NDHX identifier registry; the MPI treats "PHN scheme" as configuration (issuer URI + validator function), so adopting a national format is a config change, not a migration (tracked as an open item with 00 §7.4's NDHX conversation).
- FHIR representation: `Patient.identifier` with system `https://fhir.medagent.health.lk/id/phn` (NamingSystem published in the IG, 03 §3; URI swapped to the national system URI when NDHX publishes one).

### 8.2 Birth enrollment (FR-7.1)

Birth event → MPI `create_lifetime_profile`: PHN issued, profile linked to the mother's MPI record (`mother_phn`), birth-registration reference field reserved (civil registration integration, 09), guardian links auto-created for recorded parents (§9), and — Phase B — the immunisation schedule generated (FR-7.3, 09). Phase A ships the MPI capability and API; the birth-registration *trigger* integration is Phase B (spec Phase 3).

### 8.3 Demographic search and deduplication

Two-stage, standard MPI practice:

1. **Deterministic:** exact PHN; exact NIC (adults); exact (normalised full name + DOB + sex + phone). Hit → same person, no review.
2. **Probabilistic (Fellegi–Sunter-style weighted scoring)** over candidate pairs selected by blocking keys (phonetic surname key + birth year; phone last-9):

| Field | Comparator | Notes |
|---|---|---|
| Names | Jaro–Winkler ≥ 0.92 on Latin transliteration | Sinhala/Tamil names vary heavily in transliteration; MPI stores name in **both native script and Latin** fields, matches on normalised Latin + a curated transliteration-equivalence list (e.g. *Mohamed/Mohammed/Mohamad*) — grown during pilot |
| DOB | exact / year+month / year-only (declining weights) | estimated DOBs (01 Jan pattern) down-weighted |
| Sex | exact | |
| Phone | exact on last 9 digits | shared family phones down-weighted |
| Address | token overlap on GN-division level | Phase B once address normalisation exists |

Score bands: **≥ upper threshold** → auto-link candidate (flagged, reversible); **middle band** → human review queue (receptionist/admin steward UI, merge or mark-distinct with survivorship rules: newest verified value wins per field, full merge history kept); **< lower** → new record. Thresholds are configuration (FR-6.2) tuned on pilot data. Every merge/split emits an `AuditEvent` and republishes the FHIR `Patient` (with `Patient.link` for merged records).

Phase A honesty: pilot volume is one hospital, so Phase A ships deterministic matching + the weighted score + review queue with *conservative* thresholds (prefer review over auto-link). EM-trained weights and a dedicated matching engine are Phase B national-scale work (09).

Search (FR-2.4) uses the same normalised columns: name (either script), PHN (check-digit validated before query), phone — receptionist search returns demographics + photo only; opening the clinical record still requires a §7 grant (queue check-in creates one).

### 8.4 MPI schema (summary)

`patients_mpi` (phn PK, nic, name_native, name_latin, dob, dob_estimated, sex, phone, address_gn, mother_phn, fhir_patient_id, ext_face_id nullable, sludi_ref nullable, status) · `guardian_links` (§9) · `mpi_merge_log` · `break_glass_grants` (§6) · `relationship_grants` materialised operational state (§7). All rows audit-logged on change.

### 8.5 SLUDI adapter (reserved, FR-7.2)

SLUDI (MOSIP-based) issues its first digital IDs Q3 2026 with rollout through end-2026 — mid-to-post pilot. The MPI therefore treats SLUDI as a **pluggable identity provider binding**, reserved now, activated when integration opens:

```python
class NationalIdAdapter(Protocol):
    async def verify(self, sludi_token_or_vid: str) -> IdAssertion   # MOSIP IDA auth/eKYC
    async def link(self, phn: str, assertion: IdAssertion) -> LinkResult
    async def unlink(self, phn: str) -> None
```

- Implementation target: MOSIP ID Authentication (IDA) APIs / e-Signet OIDC, whichever SLUDI exposes — the adapter isolates that choice.
- Binding model: `sludi_ref` stores the SLUDI **VID/token reference, never raw biometrics or UIN**, alongside verification level + timestamp; also projected as a second `Patient.identifier` (system URI assigned by SLUDI programme).
- Keycloak angle: when SLUDI offers OIDC (e-Signet), it is added as an **identity provider brokered into the `medagent` realm** for patient login — configuration, not code, thanks to realm-as-code.
- Until then, PHN is the primary identifier (locked research fact; 00 §5) and a `NoopAdapter` satisfies the interface so all call-sites exist and are tested.

## 9. Guardian proxy access (FR-5.9, FR-7.8)

- **Phase A scope: read-only.** The pilot ships guardian *viewing* of the linked child's record with a child switcher in the portal (07); booking-on-behalf, consent management by the guardian, and the automated transition-at-majority flow (courtesy notifications, account handover) move to Phase B. The link model, rights profile, and computed expiry below are implemented in full from day 1 — Phase A simply activates only the `view` right.
- `guardian_links` row: guardian PHN/account, ward PHN, relationship (mother/father/legal guardian — **both parents linkable**), rights profile (view — Phase A; book, consent-manage, join-telemedicine — Phase B), `valid_from`, `valid_until`, evidence reference (birth registration or admin-verified document).
- **Expiry at majority is computed, not scheduled:** `valid_until = min(explicit_expiry, ward_dob + 18 years)` (age of majority in Sri Lanka). The §7 decision path evaluates `valid_until` at request time, so access ends at the ward's 18th birthday even if no job runs; a courtesy job notifies both parties 30 days ahead and prompts the ward to take over the account (portal handover flow, 07 — Phase B).
- Guardian actions are audited **as the guardian** (distinct actor) on the ward's record — visible in the ward's access log after handover.
- Consent decisions made by a guardian (Phase B, per the rights phasing above) are marked as proxy-granted in the FHIR `Consent` provenance; at majority the patient is prompted to review standing consents (07).
- Court-ordered removal / custody change: admin revokes the link (FR-6.1/6.4); revocation invalidates the authz cache immediately (§7.4).
- FHIR: Phase A keeps guardian links in `app_db` (they are authorisation state); Phase B projects them as `RelatedPerson` when telemedicine guardian-join and CHDR sharing need them in clinical context (03 §3, FR-12.2).

## 10. Administration module (FR-6.1–6.4)

Admin UI lives in the web app behind the `admin` role; all operations go through core-api (never direct Keycloak console use in production).

| FR | Implementation |
|---|---|
| **FR-6.1** staff accounts, roles, departments | core-api wraps the Keycloak Admin API (its `core-api` service account holds `manage-users` on the realm only): create staff, assign matrix roles (§3), bind to `Practitioner`/`PractitionerRole` (department, facility) in FHIR. Joiner/mover/leaver: disable-in-Keycloak on leave, end-date PractitionerRole; quarterly access recertification report (08). |
| **FR-6.2** thresholds & safety rules | `app_db` config store with versioned entries + change audit: face-confidence threshold (consumed via 05 policy check), MPI match thresholds (§8.3), break-glass TTL (§6), DDI rule severity overrides (04). Changes require `loa2` (§5.2) and take effect via config-refresh pub/sub — no redeploys. |
| **FR-6.3** log & audit review | Read-only audit explorer querying `AuditEvent` (03 §5.3): filter by actor/patient/action/facility/purpose; break-glass review queue (§6.2); tamper-evidence verification job surfaces hash-chain status. Admins reviewing audit see event metadata, not clinical payloads. |
| **FR-6.4** consent & data-subject requests | Consent record browser (FHIR `Consent` versions); DSR workflow: export (bundle via `$everything`, 03 §8.1) and erasure requests with the retention-law decision tree (03 §8.2), each tracked with statutory clocks per PDPA (08). |

## 11. Session management for SSE (short-lived single-use ticket)

The prototype passed a long-lived JWT in the `EventSource` query string — logged by every proxy, cached in browser history, replayable for its full lifetime. Native `EventSource` cannot set an `Authorization` header, so the fix is a **single-use, short-lived ticket**:

1. Client calls `POST /notify/ticket` with its normal Bearer token (audience `notify-service`).
2. notify-service authorises the requested channels against the token (a doctor gets their facility queue channel; a patient gets only their own channel), then stores an opaque 128-bit random ticket in Redis: `SETEX sse:ticket:{id} 30s {sub, channels, session_id}` .
3. Client opens `GET /notify/stream?ticket={id}`; notify-service redeems with atomic `GETDEL` — **single-use** (replay gets 401), 30 s validity window covers only the connect race.
4. The stream is bound to the resolved subject for its lifetime; server closes it when the underlying Keycloak session ends (logout event) or after a 15-min max age, and the client reconnects with a fresh ticket (built into the `EventSource` reconnect handler).
5. Gateway access logs scrub the `ticket` query parameter (Traefik log field redaction) — defence in depth even though a leaked ticket is dead ≤ 30 s after issue and single-use.

The ticket is deliberately an **opaque Redis reference, not a signed JWT**: nothing to parse, nothing to leak claims from, revocation for free, and notify-service already has Redis (01 §1). The same mechanism serves the kiosk check-in event view and Phase B WebSocket upgrades.

## 12. Decisions (ADRs)

| ADR | Decision | Rationale | Alternatives rejected |
|---|---|---|---|
| I-1 | Keycloak 26.x + keycloak-config-cli realm-as-code | Reviewable, reproducible, environment-parity IAM; console drift eliminated; locked decision D8 | Hand-configured realm (undocumented drift); Terraform Keycloak provider (weaker coverage of auth-flow/ACR config than config-cli) |
| I-2 | Single `medagent` realm for staff + patients | Guardianship and clinician-as-patient cross the boundary; role/scope separation already isolates; one ACR/LoA config | Separate staff/patient realms (cross-realm brokering complexity, duplicate flows) |
| I-3 | Care-relationship authorisation in core-api decision service + Redis cache, consumed by FHIR interceptor | Relationships are minute-granular operational state — wrong altitude for tokens/roles; single decision point, cacheable, auditable; directly fixes prototype any-doctor-reads-all flaw | Patient lists in token claims (stale, unbounded size); Keycloak UMA/fine-grained permissions (server round-trips per resource, poor FHIR-search fit); OPA sidecar (extra moving part with no data advantage — reconsider Phase B if policy count grows) |
| I-4 | Break-glass as time-boxed `app_db` grant + `purposeOfUse=BTG` audit, not a Keycloak role | Instant grant/expiry, no realm mutation in emergencies, review queue trivially attaches to the grant row | Temporary Keycloak role assignment (slow, hard to time-box, pollutes IAM audit); standing "emergency" role (defeats least privilege) |
| I-5 | Step-up via Keycloak native ACR/LoA with 300 s max-age, verified server-side at commit paths | Standards-based (`acr` claim), no custom auth code, satisfies spec §4.2 step-up for e-prescribing and break-glass | Custom re-auth endpoint (bespoke crypto path); transaction signing/CIBA (Phase B consideration for remote sign-off) |
| I-6 | PHN = 11-digit Verhoeff-checked, semantics-free, scheme-as-config | Transcription-error detection; no data leakage; national-format adoption is config not migration | Embedded DOB/facility digits (leaks data, breaks on change); UUID-only (human-unusable at a kiosk) |
| I-7 | MPI dedup: deterministic pass + conservative Fellegi–Sunter scoring + human review queue in Phase A | Pilot volume favours precision + stewardship over automation; framework scales to EM-trained weights Phase B | Auto-merge on score (irreversible harm risk); dedicated MPI product day 1 (operational overhead unjustified at pilot scale) |
| I-8 | SLUDI as pluggable `NationalIdAdapter` (MOSIP IDA/e-Signet target) + future Keycloak IdP brokering; `NoopAdapter` until integration opens | SLUDI timing (Q3 2026 first IDs) is outside our control; adapter keeps all call-sites real and tested; locked decision + spec FR-7.2 "adapter reserved" | Blocking pilot on SLUDI; building against unpublished APIs |
| I-9 | Guardian expiry computed at decision time from ward DOB (majority), not a scheduled revocation job | Fail-safe: access ends even if jobs fail; job only handles courtesy notification/handover | Cron-driven revocation as the enforcement mechanism (job failure = unlawful access) |
| I-10 | SSE auth via single-use 30 s opaque Redis ticket exchanged for the stream | Fixes JWT-in-query prototype flaw; native EventSource compatible; free revocation; no claim leakage | JWT in query (logged, replayable); cookie-bound SSE (CSRF surface, breaks kiosk contexts); switching to WebSocket solely for the header (churn without need) |

## Cross-references

- Gateway routing and network isolation: 01-system-architecture.md
- FHIR authz/consent/audit interceptors consuming §7 decisions: 03-fhir-data-platform.md
- Sign-off interrupt flow carrying step-up tokens: 04-ai-agent-platform.md
- Face-service webhook HMAC contract and enrolment consent gate: 05-face-recognition-integration.md
- Admin and portal UX for §9–§11: 06-doctor-workspace-frontend.md, 07-patient-portal-pwa.md
- PDPA analysis, DPIA, retention, hash-chain anchoring: 08-security-privacy-compliance.md
- SLUDI/NDHX/HHIMS national integration timelines: 09-integrations-national.md
