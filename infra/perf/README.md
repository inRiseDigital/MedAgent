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
| Record load | `record-load.js` (S2+) | 50 VUs opening patient summaries | full summary p95 < 2 s (NFR-2); HAPI pool no exhaustion |
| Portal skim | `portal-skim.js` (S3+) | 100 VUs patient PWA browsing | p95 < 1.5 s page data; error rate < 0.1 % |
| Soak | `soak.js` (S5+) | 2 h mixed profile at pilot load ×2 | no memory growth / connection leaks; SSE reconnects sane |

Only `checkin-burst.js` exists in S1 (skeleton). Run:

```sh
k6 run -e BASE_URL=https://staging.example \
       -e FACE_WEBHOOK_HMAC_SECRET=... -e FACE_WEBHOOK_HMAC_KEY_ID=key-1 \
       checkin-burst.js
```

Secrets come from the environment (SOPS-decrypted in CI) — never hardcoded in
scenario files.
