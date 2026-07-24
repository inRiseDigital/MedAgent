# Operational runbooks (S6)

Practical procedures for running the pilot stack: backup/restore, the verified
restore drill, and service-degradation responses. Pairs with
[SECURITY-REVIEW.md](SECURITY-REVIEW.md) and the design-time ops standards in
[solution/10-devops-infrastructure.md](solution/10-devops-infrastructure.md).

Commands below target the local compose stack (`docker compose -f
infra/compose/docker-compose.yml`). On staging/pilot the same `pg_dump`/
`pg_restore` semantics apply through the managed Postgres tooling.

## 1. What holds state

| Database | Owner service | Contents | Loss impact |
|----------|---------------|----------|-------------|
| `hapi_db` | HAPI FHIR | All clinical FHIR resources (Patient, Condition, Med, Obs, AuditEvent, …) | **Critical** — the medical record |
| `app_db` | core-api / agent / notify | MPI (`patients_mpi`), audit outbox, queue, consent/feedback state | **Critical** — identity + audit trail |
| `keycloak` | Keycloak | Users, sessions, realm runtime state | High — staff/patient identities (realm structure is re-appliable from `platform/keycloak/realm/*.yaml`, user data is not) |

Redis is a cache/broker (sessions, consent decisions, SSE tickets, event
streams) — **not** a source of truth; it is intentionally not backed up.

## 2. Backup

Dump each stateful DB (custom format, portable, owner-independent):

```sh
PG="docker compose -f infra/compose/docker-compose.yml exec -T postgres"
STAMP=$(date +%Y%m%d-%H%M%S)   # supply the timestamp from your shell
for db in app_db hapi_db keycloak; do
  $PG sh -lc "pg_dump -U postgres --no-owner --no-privileges -Fc $db" > backup-$db-$STAMP.dump
done
```

- Schedule: nightly full + WAL/PITR on staging (10 §5); retention per the data
  policy. Store off-host, encrypted.
- `--no-owner --no-privileges` makes a dump restorable into a fresh instance
  whose service roles do not yet exist (roles are created by bootstrap, not the
  dump).

## 3. Restore

Into a fresh/scratch database (never restore over a live DB without a
maintenance window):

```sh
PG="docker compose -f infra/compose/docker-compose.yml exec -T postgres"
# DROP/CREATE DATABASE must each be their own statement — they cannot run
# inside a transaction block (psql batches `;`-joined statements into one).
$PG psql -U postgres -tAc "CREATE DATABASE app_db_restore"
$PG sh -lc "pg_restore -U postgres --no-owner --no-privileges -d app_db_restore" < backup-app_db-<stamp>.dump
```

Full recovery order after total loss: (1) start Postgres, (2) restore all three
DBs, (3) re-apply the Keycloak realm (`platform/keycloak/realm/*.yaml` via
config-cli) if `keycloak` was rebuilt rather than restored, (4) start services,
(5) verify readiness + run the smoke checks in §5.

## 4. Restore drill — VERIFIED 2026-07-23

Non-destructive drill: dump the live DBs, restore into scratch copies, compare
row counts, drop the scratch copies. Result:

| Table | Live | Restored | |
|-------|------|----------|--|
| `app_db.patients_mpi` | 3 | 3 | ✓ |
| `app_db.audit_outbox` | 15 | 15 | ✓ |
| `hapi_db.hfj_resource` | 33 | 33 | ✓ |

`pg_restore` exit 0 for both dumps; scratch DBs dropped after. **Drill: PASS.**
Re-run before pilot go-live and after any schema migration. TODO: add
audit-chain hash verification once the hash-chaining interceptor lands (03 §5.4).

## 5. Degradation responses (built behaviours)

| Symptom | Built behaviour | Operator action |
|---------|-----------------|-----------------|
| **HAPI FHIR down** | Reads/writes error; core-api retries once on a dropped connection (shared pool) then surfaces the error — care is never silently wrong. UI shows "Record summary unavailable" + chat errors | Check `fhir` container + `hapi_db`; restart HAPI; watch core-api logs for `RemoteProtocolError` clearing. **If HAPI boots but every search returns 400/500 after a recreate:** see "HAPI won't serve" below |
| **HAPI won't serve after recreate** (search 400 "does not know how to handle", or 500 `seq_search` syntax) | The base image `hapiproject/hapi:v8.10.0-3` needs its OWN bundled config for search routing, and Postgres needs the HAPI Postgres dialect (base default is H2) | Ensure the `fhir` service env keeps `SPRING_CONFIG_LOCATION: optional:classpath:/application.yaml` (base config, NOT only our file) **and** `SPRING_JPA_PROPERTIES_HIBERNATE_DIALECT: ca.uhn.fhir.jpa.model.dialect.HapiFhirPostgresDialect`. Do NOT point SPRING_CONFIG_LOCATION solely at a custom application.yaml — it discards the JPA/provider config |
| **core-api down** | Web summary card + queue render a degraded banner, don't hard-fail; chat/proposals unavailable | Restart core-api; check `app_db` + Redis ACL user health |
| **notify-service down** | Events buffer in Redis streams (TTL); UI falls back to queue polling; SSE reconnects on recovery | Restart; confirm SSE `/notify/stream` resumes |
| **Keycloak down / JWKS unreachable** | New logins fail; existing sessions valid until token expiry; JWKS refresh is single-flight so recovery doesn't stampede | Restart Keycloak; a burst of 401s right after recovery is expected as the cache re-warms once |
| **Redis down** | Sessions/consent-cache/SSE-tickets unavailable → logins + live events degrade; DB truth intact | Restart Redis; re-apply ACL users if the instance was recreated |
| **Anthropic API unreachable** | Chat answers fail; the **deterministic Rx-safety engine is unaffected** (no LLM in the safety path) — prescribing safety still holds | Inform clinicians chat is degraded; record review continues via the summary card + FHIR |

## 6. Observability

The observability stack is a compose **profile** (off by default). Start it:

```sh
docker compose -f infra/compose/docker-compose.yml --profile observability up -d
```

- **Grafana** — http://localhost:3001 (dev creds `admin` / `$GRAFANA_ADMIN_PASSWORD`).
  Dashboard **"Golden Signals — per service"** (Traffic RPS / 5xx error rate /
  latency p50-p95-p99 / CPU+memory), provisioned as code.
- **Prometheus** — http://localhost:9090. Targets: `core-api`, `agent-service`,
  `notify-service`, `gateway` should all be **UP** (Status → Targets).
- Each service exposes `/metrics` (prometheus format) on its app port; the
  gateway exposes Traefik metrics on internal `:8082`.
- Golden-signals metric sources: `http_requests_total`,
  `http_request_duration_seconds_bucket`, `process_cpu_seconds_total`,
  `process_resident_memory_bytes` (all carry a `service` label from the scrape
  config).
- **Not yet wired:** OTLP trace/log export to Tempo/Loki (the `otel-collector`
  target stays down until `configure_telemetry` adds the trace exporter). Metrics
  are fully live.

Stop it (frees resources) without touching the app stack:
`docker compose -f infra/compose/docker-compose.yml --profile observability down`.

## 7. Everyday checks

- Stack health: `docker compose ps` (all `healthy`; gateway/keycloak may report
  `unhealthy` on their container healthcheck while serving fine — verify via a
  real request, not just the flag).
- Audit backlog: `SELECT count(*) FROM audit_outbox WHERE NOT dispatched;` in
  `app_db` should trend to ~0 (the dispatch loop drains it).
- Record load p95: `k6 run -e BASE_URL=https://localhost -e INSECURE_TLS=1
  -e VUS=30 -e DURATION=15s infra/perf/record-load.js` — summary p95 < 2 s.
