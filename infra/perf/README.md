# Performance & load testing (k6 — ADR DI-7)

Scenarios per 10-devops-infrastructure.md §8, run **against staging**: a
baseline profile on every staging deploy (smoke thresholds) and the full suite
weekly + before pilot go-live. Thresholds encode the NFRs — a breach fails the
run. Results export to Prometheus and trend on the golden-signals/HAPI
dashboards; regressions vs the previous run are ticket-severity.

| Scenario | File | Shape | Asserts |
|---|---|---|---|
| Check-in burst | `checkin-burst.js` | 30 signed webhook events in 60 s, doctors' SSE connected | platform path p95 < 300 ms (NFR-1 share); zero dropped events; queue consistency |
| Chat concurrency | `chat-concurrency.js` (S2+) | 20 concurrent doctor chats, recorded-LLM mode | first-token p95 < 2 s; no stream stalls; memory stable |
| Record load | `record-load.js` ✅ | N VUs opening patient summaries + demographic search | full summary p95 < 2 s (NFR-2); search p95 < 500 ms (03 §6.2); HAPI pool no exhaustion (error rate ~0) |
| Portal skim | `portal-skim.js` (S3+) | 100 VUs patient PWA browsing | p95 < 1.5 s page data; error rate < 0.1 % |
| Soak | `soak.js` (S5+) | 2 h mixed profile at pilot load ×2 | no memory growth / connection leaks; SSE reconnects sane |

`checkin-burst.js` (skeleton) and `record-load.js` exist. Run the record-load
gate against a running stack:

```sh
k6 run -e BASE_URL=https://localhost -e INSECURE_TLS=1 \
       -e VUS=30 -e DURATION=15s record-load.js
```

Secrets come from the environment (SOPS-decrypted in CI) — never hardcoded in
scenario files. `record-load.js` defaults to the dev throwaway staff account and
demo PHN; override `KC_USERNAME`/`KC_PASSWORD`/`PHN` for other environments.

## Findings

- **Connection pooling (fixed 2026-07-23).** The first record-load run surfaced
  `httpx.RemoteProtocolError: Server disconnected` → intermittent 500s under
  load: core-api created a **new httpx client per request**, so each reused
  keep-alive connections HAPI had already closed. Fix: a single shared, bounded
  pool per base URL with retry-once on a dropped connection (`app/fhir_client.py`),
  plus single-flight JWKS refresh (`app/auth.py`) to stop a cold-cache burst
  stampeding Keycloak into transient 401s. After the fix, a 30-VU / 15 s run via
  the gateway is **0 % errors, summary p95 1.72 s (< 2 s NFR-2), search p95
  ~100 ms**. The full 3×-pilot NFR gate still runs on staging (03 §157) — a
  single-node dev box is not staging-representative, and long Windows-host runs
  add false client-side connection failures (see the note in `record-load.js`).
