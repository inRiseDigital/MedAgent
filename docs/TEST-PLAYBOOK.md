# MedAgent — hands-on test playbook

How every flow works and exactly how to test it yourself, step by step. Two
tracks: **UI** (click through the browser) and **API** (copy-paste curl). Run the
curl blocks in **Git Bash** (not PowerShell).

## 0. Start the stack & check health

```bash
cd d:/Git/medagent-platform
docker compose -f infra/compose/docker-compose.yml up -d        # start everything
# wait ~60s for HAPI FHIR to boot, then:
curl -s -o /dev/null -w "core-api %{http_code}\n" http://localhost:8001/healthz
curl -s -o /dev/null -w "keycloak %{http_code}\n" http://localhost:8081/auth/realms/medagent/.well-known/openid-configuration
curl -s -o /dev/null -w "web      %{http_code}\n" http://localhost:3000
```
All should print `200`. (Optional: `--profile seed up seed` loads ~1,000 Synthea patients.)

**Logins** (username / password): `dr_demo` / `dev-only-dr_demo` (doctor),
`reception_demo` / `dev-only-reception_demo`, `patient_demo` / `dev-only-patient_demo`.

**Known demo patients:** Baby Perera `42901168225` (child, has guardian),
Nimal Perera `55246820131` (mother/guardian), Sunil Fernando `70011223344` (adult).

### Token helper (paste once per Git Bash session)
```bash
tok() { curl -s -X POST "http://localhost:8081/auth/realms/medagent/protocol/openid-connect/token" \
  -d grant_type=password -d client_id=dev-cli -d username=${1:-dr_demo} -d password=dev-only-${1:-dr_demo} \
  -d scope=openid | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])"; }
TOK=$(tok dr_demo); A="authorization: Bearer $TOK"; J="content-type: application/json"
echo "${TOK:0:20}..."   # non-empty = good
```

---

## PART 1 — Doctor workspace (browser)

Open **http://localhost:3000** → you're redirected to login → sign in as `dr_demo`.

### 1.1 Live queue & check-in
- Nav **Live queue**. You see waiting patients (SSE-live; the connection badge shows live/degraded).
- To add someone: `curl -s -X POST http://localhost:8001/api/v1/queue/check-in -H "$A" -H "$J" -d '{"patient":"55246820131","facility_id":"pilot-hospital-1"}'` → the row appears in the queue **without refresh**.

### 1.2 Patient search → session
- Nav **Patients** → type a name (e.g. `Perera`) or a PHN → click a result.
- The **patient session** opens: summary rail (allergies, problems, meds), **Safety flags** card (if any), chat, clinical entry, prescription sign-off. For a child you also get the **Child health** card; if imaging/labs exist you get **Imaging** and **Lab results** cards.

### 1.3 Ambient safety flags (deterministic)
- Open a patient with a penicillin allergy + an interacting med → the **Safety flags** card lists them (allergy, drug–drug, critical lab) with citations — computed server-side, no typing.

### 1.4 AI chat + voice command
- In the chat, type *"Summarise this patient's active problems and meds with citations"* → streamed, cited answer. (If you see a quota message, set `AGENT_LLM_MODE=stub` on agent-service for offline canned replies.)
- **Voice (3.3):** click the **mic** next to the chat box, say **"give me the summary"** → it auto-sends a cited-summary request. Say anything else → it dictates into the input for you to review. *(Chrome/Edge only; the mic button is hidden on unsupported browsers.)*

### 1.5 Clinical entry + voice dictation
- **Clinical entry** card → pick a tab:
  - **Diagnosis**: `Type 2 diabetes mellitus`, ICD-10 `E11` → **Save** → writes a FHIR Condition (audited).
  - **Vital**: `Body weight`, value `72`, unit `kg` → Observation.
  - **Note**: click the **mic (3.2)** and dictate, or type → DocumentReference.
  - **Lab order** / **Imaging**: creates a ServiceRequest.
- Each save returns a committed reference and is audited.

### 1.6 Prescription sign-off (Rx-safety: pass / warn / block)
- **Prescription** panel → enter a drug + dose → **Prescreen**:
  - `Paracetamol`, 500 mg → **PASS**.
  - `Cephalexin` on a penicillin-allergic patient → **WARN** (cross-reactivity) → needs an override reason to commit.
  - `Amoxicillin` on an amoxicillin-allergic patient → **BLOCK** (hard stop, cannot commit).
- The verdict is computed by the deterministic engine; the LLM never overrides it.

### 1.7 Referral inbox (worklist + actions)
- Nav **Referrals**. Switch facility with the chips (top-right): `teaching-hospital`, `moh-epi-unit`, …
- Each card shows specialty, priority, patient, reason. Click **Accept** → **Complete** (or **Reject**). The list refreshes; toggle **Include closed** to see finished ones.
- Illegal actions are blocked server-side (e.g. accept an already-completed one → error shown).

### 1.8 National dashboard
- Nav **Dashboard**: KPI tiles (patients, labs, imaging, immunizations, referrals, notifiable cases), **outbreak early-warning** (colour-coded none/watch/alert), **facility capacity** table.

---

## PART 2 — Patient portal (browser)

Open **http://localhost:3000/portal** in a private window → sign in as `patient_demo`.
- See your own record: problems, meds, allergies, appointments, **lab results** (critical flagged).
- **Export** → opens a printable visit summary (Print → Save as PDF).
- **Consent** toggle → flips face-recognition consent (writes a FHIR Consent, audited).
- **Access log** → who accessed your record (from the audit trail).

---

## PART 3 — National modules (API, copy-paste)

### 3.1 Lab network — full lifecycle
```bash
# create a lab order (write-back), then drive the specimen state machine
SR=$(curl -s -X POST http://localhost:8001/api/v1/proposals/commit -H "$A" -H "$J" \
  -d '{"kind":"lab_order","patient":"55246820131","payload":{"text":"Serum potassium","loinc":"2823-3"}}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['committed'].split('/')[1])")
echo "order $SR"
curl -s "http://localhost:8001/api/v1/lab/worklist?patient=55246820131" -H "$A" | python -m json.tool | head
curl -s -X POST "http://localhost:8001/api/v1/lab/$SR/advance" -H "$A" -H "$J" -d '{"to":"collected"}'   # assigns accession + Specimen
curl -s "http://localhost:8001/api/v1/lab/$SR/label" -H "$A" | head -c 120     # Code128 SVG barcode
# advance to received, pull to the analyzer, push a CRITICAL result:
for st in in-transit received; do curl -s -X POST "http://localhost:8001/api/v1/lab/$SR/advance" -H "$A" -H "$J" -d "{\"to\":\"$st\"}" >/dev/null; done
ACC=$(curl -s "http://localhost:8001/api/v1/lab/worklist?patient=55246820131" -H "$A" | python -c "import sys,json;print([o for o in json.load(sys.stdin) if o['order_id']=='$SR'][0]['accession'])")
curl -s -X POST "http://localhost:8001/api/v1/lab/analyzer/pull?accession=$ACC" -H "$A"
curl -s -X POST "http://localhost:8001/api/v1/lab/analyzer/result" -H "$A" -H "$J" -d "{\"accession\":\"$ACC\",\"loinc\":\"2823-3\",\"value\":6.5}"
# release: 6.5 is CRITICAL -> requires validation
curl -s -X POST "http://localhost:8001/api/v1/lab/$SR/release" -H "$A" -H "$J" -d '{"validated_by":"dr_demo"}'
curl -s "http://localhost:8001/api/v1/lab/reports?patient=55246820131" -H "$A" | python -m json.tool
```
**Expect:** accession `MA…`, printable barcode, a critical-value alert, and a released DiagnosticReport with `critical:true`.

### 3.2 Child health — birth → immunization → growth → CHDR
```bash
# immunization schedule (auto-generated from birth date)
curl -s "http://localhost:8001/api/v1/patients/42901168225/immunizations" -H "$A" | python -m json.tool | head -30
# record BCG given -> status flips to "given", overdue drops
curl -s -X POST http://localhost:8001/api/v1/patients/42901168225/immunizations -H "$A" -H "$J" -d '{"key":"bcg"}'
# growth: a LOW weight flags underweight/stunted
curl -s -X POST http://localhost:8001/api/v1/patients/42901168225/growth -H "$A" -H "$J" -d '{"weight_kg":2.0,"height_cm":44,"date":"2026-07-20"}'
# the aggregate the clinician/parent/midwife share:
curl -s "http://localhost:8001/api/v1/patients/42901168225/chdr" -H "$A" | python -m json.tool
```
**Expect:** overdue vaccines listed; recording BCG → `given`; 2.0 kg → `underweight`+`stunted`; CHDR shows the consolidated alerts.

### 3.3 Referrals — closed loop
```bash
R=$(curl -s -X POST http://localhost:8001/api/v1/referrals -H "$A" -H "$J" \
  -d '{"patient":"55246820131","to_facility":"teaching-hospital","specialty":"Cardiology","reason":"Murmur","priority":"urgent"}')
TID=$(echo "$R" | python -c "import sys,json;print(json.load(sys.stdin)['task_id'])")
curl -s "http://localhost:8001/api/v1/referrals/inbox?facility=teaching-hospital" -H "$A" | python -m json.tool
curl -s -X POST "http://localhost:8001/api/v1/referrals/$TID/act" -H "$A" -H "$J" -d '{"action":"accept"}'
curl -s -X POST "http://localhost:8001/api/v1/referrals/$TID/act" -H "$A" -H "$J" -d '{"action":"complete"}'
curl -s -X POST "http://localhost:8001/api/v1/referrals/$TID/act" -H "$A" -H "$J" -d '{"action":"accept"}'   # expect 409 (illegal)
```

### 3.4 Scheduling — auto-book by urgency
```bash
curl -s -X POST http://localhost:8001/api/v1/schedule/slots -H "$A" -H "$J" \
  -d '{"facility":"base-hospital","specialty":"Cardiology","slots":[{"start":"2026-08-10T09:00:00Z","end":"2026-08-10T09:20:00Z"},{"start":"2026-08-10T10:00:00Z","end":"2026-08-10T10:20:00Z"}]}'
curl -s -X POST http://localhost:8001/api/v1/schedule/waitlist -H "$A" -H "$J" -d '{"patient":"55246820131","facility":"base-hospital","specialty":"Cardiology","urgency":"routine"}'
curl -s -X POST http://localhost:8001/api/v1/schedule/waitlist -H "$A" -H "$J" -d '{"patient":"70011223344","facility":"base-hospital","specialty":"Cardiology","urgency":"urgent"}'
curl -s -X POST "http://localhost:8001/api/v1/schedule/auto-book?facility=base-hospital&specialty=Cardiology" -H "$A" | python -m json.tool
curl -s "http://localhost:8001/api/v1/schedule/waiting-times" -H "$A" | python -m json.tool
```
**Expect:** the **urgent** patient takes the earliest 09:00 slot even though added last.

### 3.5 Telemedicine — guardian join + e-Rx
```bash
S=$(curl -s -X POST http://localhost:8001/api/v1/telemedicine/sessions -H "$A" -H "$J" -d '{"patient":"42901168225","reason":"Follow-up"}')
echo "$S" | python -m json.tool    # note the room + join tokens (patient, clinician, GUARDIAN)
SID=$(echo "$S" | python -c "import sys,json;print(json.load(sys.stdin)['session_id'])")
GT=$(echo "$S"  | python -c "import sys,json;d=json.load(sys.stdin);print(next(j['token'] for j in d['join'] if j['role']=='guardian'))")
curl -s "http://localhost:8001/api/v1/telemedicine/sessions/$SID/join?token=$GT" -H "$A" | python -m json.tool  # guardian joins
curl -s "http://localhost:8001/api/v1/telemedicine/sessions/$SID/join?token=$GT" -H "$A"    # reuse -> 401 (single-use)
ENC=$(curl -s -X POST "http://localhost:8001/api/v1/telemedicine/sessions/$SID/start" -H "$A" | python -c "import sys,json;print(json.load(sys.stdin)['encounter_id'])")
curl -s -X POST "http://localhost:8001/api/v1/telemedicine/sessions/$SID/complete?encounter_id=$ENC" -H "$A"
# post-consult e-Rx (screened, linked to the encounter):
curl -s -X POST http://localhost:8001/api/v1/proposals/commit -H "$A" -H "$J" \
  -d "{\"kind\":\"prescription\",\"patient\":\"42901168225\",\"encounter_id\":\"$ENC\",\"payload\":{\"drug\":\"Paracetamol\",\"dose_text\":\"120mg QID\",\"dose_mg_per_day\":480}}"
```

### 3.6 Imaging triage — urgent auto-routes to referrals
```bash
IO=$(curl -s -X POST http://localhost:8001/api/v1/proposals/commit -H "$A" -H "$J" \
  -d '{"kind":"imaging_order","patient":"55246820131","payload":{"text":"CXR"}}' | python -c "import sys,json;print(json.load(sys.stdin)['committed'].split('/')[1])")
curl -s -X POST "http://localhost:8001/api/v1/imaging/$IO/report" -H "$A" -H "$J" \
  -d '{"modality":"cxr","body_site":"chest","findings":[{"text":"Large left pneumothorax","confidence":0.94}],"impression":"Tension pneumothorax"}' | python -m json.tool
curl -s "http://localhost:8001/api/v1/referrals/inbox?facility=teaching-hospital" -H "$A" | python -c "import sys,json;print([i['reason'] for i in json.load(sys.stdin)['items']])"
```
**Expect:** flag `urgent`, an auto-referral to Respiratory that shows in the teaching-hospital inbox. Try a normal finding (`"Lungs clear"`, conf `0.97`) → `normal`, no referral; a low-confidence one (`0.3`) → `needs_review:true`.

### 3.7 Notifiable disease + DHIS2 feed
```bash
curl -s -X POST http://localhost:8001/api/v1/registry/report -H "$A" -H "$J" -d '{"patient":"55246820131","text":"Dengue fever","icd10":"A90"}' | python -m json.tool
curl -s -X POST http://localhost:8001/api/v1/registry/report -H "$A" -H "$J" -d '{"patient":"70011223344","text":"Essential hypertension","icd10":"I10"}'  # -> notifiable:false
curl -s "http://localhost:8001/api/v1/registry/cases?disease=dengue" -H "$A" | python -m json.tool
curl -s "http://localhost:8001/api/v1/registry/feed" -H "$A" | python -m json.tool        # DHIS2 dataValueSet
curl -s "http://localhost:8001/api/v1/referrals/inbox?facility=moh-epi-unit" -H "$A" | python -m json.tool   # the surveillance alert
curl -s "http://localhost:8001/api/v1/analytics/outbreak" -H "$A" | python -m json.tool    # signal escalation
```

### 3.8 Audit trail — tamper-evident
```bash
curl -s -X POST http://localhost:8001/internal/audit/dispatch          # flush the outbox -> FHIR AuditEvents
curl -s http://localhost:8001/internal/audit/verify | python -m json.tool   # intact:true
curl -s "http://localhost:8001/api/v1/audit/access-log?patient=55246820131" -H "$A" | python -m json.tool
```
**Expect:** `intact:true`. (Every write above added audited events; the chain stays intact and fork-proof.)

---

## PART 4 — Automated tests (prove the logic)

```bash
# Python unit tests (run inside the containers; pytest is installed as root)
docker compose -f infra/compose/docker-compose.yml exec -u root core-api    sh -lc 'cd /app && /venv/bin/python -m pytest -q'
docker compose -f infra/compose/docker-compose.yml exec -u root agent-service sh -lc 'cd /app && /venv/bin/python -m pytest -q'
# Expect: core-api 40 passed, agent-service 12 passed.

# Web type-check (all UI):
docker compose -f infra/compose/docker-compose.yml exec web sh -lc 'cd /repo/apps/web && node_modules/.bin/tsc --noEmit && echo TYPECHECK-OK'

# FHIR interceptor (Java) tests:
docker run --rm -v "$(pwd -W)/platform/fhir/interceptors":/build -v medagent_m2:/root/.m2 \
  -w /build maven:3.9-eclipse-temurin-17 mvn -B -o test
# Expect: BUILD SUCCESS, AuthzInterceptorTest 14 passed.
```
(On Git Bash prefix the `docker run` with `MSYS_NO_PATHCONV=1` if paths mangle.)

---

## What "good" looks like (quick checklist)

- [ ] All 3 health checks 200; web login works.
- [ ] Queue row appears live on check-in.
- [ ] Rx-safety: paracetamol PASS, penicillin→cephalexin WARN, amoxicillin-on-allergy BLOCK.
- [ ] Lab: critical value requires validation; report released with `critical:true`.
- [ ] Child: BCG recorded → `given`; 2.0 kg → `underweight`.
- [ ] Referral: accept→complete works; re-accept → 409.
- [ ] Schedule: urgent patient wins the earliest slot.
- [ ] Telemedicine: guardian joins; reused token → 401.
- [ ] Imaging: pneumothorax → urgent + referral in inbox.
- [ ] Registry: dengue notifiable + epi alert; hypertension not notifiable.
- [ ] Audit: `verify` → `intact:true`.
- [ ] Tests: core-api 40, agent 12, web tsc OK, interceptor 14.
