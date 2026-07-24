# Verification guide — what's built & how to check it

A step-by-step checklist to verify every delivered capability yourself. Work top
to bottom; each section says **what it is**, **how to check**, and **what you
should see**.

## 0. Prerequisites

```sh
cd d:/Git/medagent-platform
# The whole stack:
docker compose -f infra/compose/docker-compose.yml ps
```
**Expect:** `postgres, redis, keycloak, fhir, core-api, agent-service,
notify-service, web, gateway, mailpit` all `Up`. (`gateway`, `keycloak`, `fhir`
may show `unhealthy` on their *container* healthcheck while serving fine — verify
by real requests below, not the flag.)

**Reference facts used throughout:**
- App URL (browser): **https://localhost** — self-signed cert in dev, click through the warning.
- Logins (realm `medagent`): doctor **`dr_demo`** / `dev-only-dr_demo` · patient **`patient_demo`** / `dev-only-patient_demo` · receptionist **`reception_demo`** / `dev-only-reception_demo`.
- Demo patient: **Nimal Perera**, PHN **55246820131** (diabetes + hypertension, on Metformin, Penicillin allergy).
- Direct service ports (dev convenience): core-api `:8001`, agent-service `:8002`, notify-service `:8003`, Keycloak `:8081/auth`, Prometheus `:9090`, Grafana `:3001`, Mailpit `:8025`.

**Mint a doctor token (used by several API checks below):**
```sh
TOK=$(curl -s -X POST "http://localhost:8081/auth/realms/medagent/protocol/openid-connect/token" \
  -d grant_type=password -d client_id=dev-cli \
  -d username=dr_demo -d password=dev-only-dr_demo -d scope=openid \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
echo "token length: ${#TOK}"   # ~1300
```

---

## 1. Identity & login (Keycloak OIDC + BFF)
**What:** Keycloak OIDC with a server-side BFF — the browser never holds tokens.

**Check (browser):** open https://localhost → you're redirected to Keycloak →
log in as `dr_demo` → you land back in the app. Open DevTools → Application →
Cookies: you see a session cookie, **no JWT/access token** in the browser.

**Check (API):** the token mint above returns a ~1300-char JWT. An unauthenticated
call is refused:
```sh
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8001/api/v1/patients?name=Perera -H "authorization: Bearer bad"
```
**Expect:** `401`.

---

## 2. Live queue (FR-2.1) + check-in
**What:** real-time patient queue; face **and** manual (no-biometrics) check-in.

**Check (browser):** log in as `dr_demo` → **Live queue** in the sidebar.
**Check (manual check-in, API):**
```sh
curl -s -X POST http://localhost:8001/api/v1/queue/check-in \
  -H "authorization: Bearer $TOK" -H "content-type: application/json" \
  -d '{"phn":"55246820131","facility_id":"pilot-hospital-1","source":"manual"}' | python -m json.tool
```
**Expect:** a queue entry JSON (state `waiting`, `source: manual`). This is the
"enter without face recognition" path.

---

## 3. Patient search (FR-2.4)
**What:** find a patient by name / PHN / phone; opening requires a care grant.

**Check (browser):** as `dr_demo` → **Patients** → type `Perera` (or `55246820131`,
or `0771234567`) → Nimal Perera appears → click → patient workspace opens.

**Check (API):**
```sh
curl -s "http://localhost:8001/api/v1/patients?name=Perera" -H "authorization: Bearer $TOK" | python -m json.tool
```
**Expect:** one result, Nimal Perera, with `phn_display "552 468 201 31"`.

---

## 4. Patient summary card (FR-2.2)
**What:** at-a-glance card — demographics, allergy chips (red for high), active
problems, active meds — from one core-api summary endpoint.

**Check (browser):** open Nimal's workspace → left card shows age/sex, a **red
Penicillin allergy chip**, problems (diabetes, hypertension), Metformin.

**Check (API):**
```sh
curl -s http://localhost:8001/api/v1/patients/55246820131/summary -H "authorization: Bearer $TOK" | python -m json.tool
```
**Expect:** JSON with `patient`, `problems`, `medications`, `allergies` (Penicillin,
criticality high), `vitals`, `appointments`.

---

## 5. Conversational clinical agent with citations (FR-2.6, real Claude over FHIR)
**What:** multi-turn chat grounded in the FHIR record; every clinical claim
carries a `[source: ResourceType/id]` citation; separates record facts from
`[general knowledge]`.

**Check (browser):** in Nimal's workspace chat, ask:
> Give me the full picture and tell me if amoxicillin is safe.

**Expect:** streamed answer that (a) pulls multiple cited resources, (b) flags
**AVOID amoxicillin** due to the penicillin (beta-lactam) allergy, (c) marks
general medical facts as `[general knowledge]`, (d) ends noting it needs your
sign-off. (This calls the real Anthropic API.)

---

## 6. Deterministic Rx-safety engine + eval gate (ADR AG-2)
**What:** drug safety is computed by a **deterministic engine** (not the LLM);
the LLM only narrates. CI fails if the engine misses any golden case.

**Check (eval gate):**
```sh
docker compose -f infra/compose/docker-compose.yml exec -T agent-service python -m evals.run
```
**Expect:** `rx_safety 23/23 (100%) ... eval-gate: PASS`, exit 0.

**Check (screen an interaction, API):**
```sh
curl -s -X POST http://localhost:8002/api/v1/rx-safety/screen \
  -H "authorization: Bearer $TOK" -H "content-type: application/json" \
  -d '{"proposed_drug":"ibuprofen","current_meds":["warfarin"],"allergies":[]}' | python -m json.tool
```
**Expect:** `verdict: block`, codes include `DDI_MAJOR` (warfarin + NSAID bleed risk).

---

## 7. Write-intent routing + safety-gated sign-off
**What:** "prescribe/start/give X" makes the agent **draft** a prescription →
deterministic screen → staged sign-off card. A `block` verdict cannot be committed.

**Check (browser):** in chat, type:
> prescribe amoxicillin 500mg

**Expect:** a **proposal card** appears with a **BLOCK** verdict (penicillin
allergy) — no free-text commit, and the block cannot be signed. Try a safe drug
(e.g. "prescribe paracetamol 500mg") → card shows pass/warn and a **Sign & commit**
action; signing writes a MedicationRequest to FHIR and audits it.

---

## 8. Audit trail + patient access log (FR-5.8)
**What:** every write/export becomes a FHIR AuditEvent; patients see a
plain-language log.

**Check (API):**
```sh
curl -s -X POST http://localhost:8001/internal/audit/flush >/dev/null   # drain outbox now
curl -s "http://localhost:8001/api/v1/audit/access-log?patient=55246820131" -H "authorization: Bearer $TOK" | python -m json.tool | head -40
```
**Expect:** entries with `action` (C/R/U/D/E) and `type` (e.g. `proposal_committed`,
`record_exported`).
**Check (browser):** log in as `patient_demo` → portal → **"Who accessed my record"**.

---

## 9. Patient portal (FR-5.1/5.3), consent (FR-5.2), export (FR-5.6)
**What:** patient sees their own record, toggles face-check-in consent, downloads
their record.

**Check (browser):** log in as **`patient_demo`** → portal shows Nimal's problems,
meds, allergies, appointments, access log. Toggle **Face check-in consent** (takes
effect immediately). **"Download my record"** → *Printable summary* opens a branded
doc (use browser Print → Save as PDF); *Export data (FHIR)* downloads a JSON bundle.

**Check (export, API):**
```sh
curl -s "http://localhost:8001/api/v1/patients/55246820131/summary/document?format=fhir" -H "authorization: Bearer $TOK" | python -c "import sys,json;d=json.load(sys.stdin);print('Bundle total:',d.get('total'))"
```
**Expect:** a FHIR `Bundle` with ~20+ entries. Each export adds an `action E`
row to the access log (§8).

---

## 10. Notifications + appointment reminders (S5)
**What:** email/SMS/push send API; a scheduled job sends appointment reminders,
deduped, respecting quiet hours.

**Check:**
```sh
curl -s -X POST http://localhost:8001/internal/notify/reminders/run -H "authorization: Bearer $TOK" | python -m json.tool
```
Then open **Mailpit** at http://localhost:8025 → you should see an "Appointment
reminder" email to Nimal. Re-running the command sends **0** (deduped).

---

## 11. Governed auto-learning loop
**What:** clinician feedback → drift metrics → human-review candidates. It **never**
auto-modifies the safety engine.

**Check (API):**
```sh
curl -s -X POST http://localhost:8002/api/v1/feedback \
  -H "authorization: Bearer $TOK" -H "content-type: application/json" \
  -d '{"kind":"rx_verdict","helpful":false,"note":"example"}' | python -m json.tool
curl -s http://localhost:8002/api/v1/feedback/metrics -H "authorization: Bearer $TOK" | python -m json.tool
```
**Expect:** feedback accepted; metrics show counts/drift. Review candidates are
written to `services/agent-service/evals/candidates/` (gitignored) for human review.

---

## 12. Performance gate (NFR-2) — record load
**What:** k6 gate proving summary p95 < 2 s; it caught + drove the connection-pool fix.

**Check:**
```sh
cd infra/perf
k6 run -e BASE_URL=https://localhost -e INSECURE_TLS=1 -e VUS=30 -e DURATION=15s record-load.js
cd ../..
```
**Expect:** all thresholds ✓ — `http_req_failed 0%`, `summary_duration p95 < 2s`,
`search_duration p95 ~100ms`. (On Windows keep runs short; long runs add false
client-side failures — see the note in the script.)

---

## 13. Security — dependency audit & secret hygiene
**What:** full-stack dep audit (0 vulns), secrets never in git, both gated in CI.

**Check (web):**
```sh
docker compose -f infra/compose/docker-compose.yml exec -T web sh -lc "cd /repo && pnpm audit --prod --audit-level high"
```
**Expect:** `No known vulnerabilities found`.
**Check (secret history):**
```sh
git log -p --all | grep -iE "sk-ant-[A-Za-z0-9]{20}" | grep -v dummy | head
```
**Expect:** no output (only the `sk-ant-dummy-not-a-real-key` placeholder exists,
which this command filters out). Real key file is gitignored:
```sh
git check-ignore infra/compose/env/agent-service.env   # prints the path = ignored
```
Full write-up: [SECURITY-REVIEW.md](SECURITY-REVIEW.md).

---

## 14. Backup / restore drill
**What:** verified dump→restore of app_db + hapi_db into scratch DBs, row counts match.

**Check:** follow [RUNBOOKS.md](RUNBOOKS.md) §3–4 (non-destructive; it restores into
throwaway `*_restore` DBs and drops them). **Expect:** `RESTORE DRILL: PASS`.

---

## 15. Observability (golden signals)
**What:** metrics from all services + gateway → Prometheus → Grafana dashboard.

**Check:**
```sh
docker compose -f infra/compose/docker-compose.yml --profile observability up -d
```
- **Prometheus** http://localhost:9090 → Status → Targets: `core-api`,
  `agent-service`, `notify-service`, `gateway` all **UP**.
- **Grafana** http://localhost:3001 (`admin` / `dev-grafana-pw`) → dashboard
  **"Golden Signals — per service"** → generate traffic (browse the app) → the
  Traffic/Latency/Errors panels populate.

---

## 16. Gateway / transport
**What:** everything behind TLS at one gateway; HAPI FHIR has no public port.

**Check:**
```sh
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/fhir/metadata 2>/dev/null || echo "no direct FHIR port (correct)"
curl -sk -o /dev/null -w "gateway https = %{http_code}\n" https://localhost/portal
```
**Expect:** HAPI is **not** reachable on a host port; the gateway serves HTTPS.

---

## Where the docs live
- Build tracker: [BUILD-PLAN.md](BUILD-PLAN.md)
- Security: [SECURITY-REVIEW.md](SECURITY-REVIEW.md) · [THREAT-MODEL.md](THREAT-MODEL.md)
- Ops: [RUNBOOKS.md](RUNBOOKS.md) · Compliance: [COMPLIANCE-PACK.md](COMPLIANCE-PACK.md)
- Design set: [docs/solution/](solution/)

## Known deferrals (by design, tracked)
- **R-1:** FHIR-boundary enforcement interceptors (app-layer authz is live; JAR builds).
- **R-3:** chat concurrency/soak load (needs a recorded-LLM harness — in progress).
- OTLP traces/logs to Tempo/Loki + Prometheus alert rules (metrics are live).
