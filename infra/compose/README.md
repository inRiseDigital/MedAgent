# Local development stack

One command from this directory (or `make up` at the repo root):

```sh
docker compose up
```

Entry point: **https://localhost** (Traefik gateway; generate locally-trusted
certs once with `mkcert -cert-file certs/localhost.pem -key-file certs/localhost-key.pem localhost` —
`certs/` is gitignored). Governing design: `docs/solution/10-devops-infrastructure.md` §2.

## Profiles (10 §2.2)

| Profile | Command | Adds |
|---|---|---|
| (default) | `docker compose up` | gateway, web, core-api, agent-service, notify-service, fhir, keycloak, postgres, redis, minio (+createbuckets), mailpit, face-sim |
| `observability` | `docker compose --profile observability up` | otel-collector, Prometheus, Tempo, Loki, Grafana (provisioned from `infra/observability/`) |
| `seed` | `make seed` | Synthea seed job (`seed/README.md`) |
| `test` | see below | integration-test runner + ephemeral overrides |

### The `test` profile

The ephemeral variant is a **separate overlay file**, `docker-compose.test.yml`
(tmpfs Postgres, randomised host ports, no persistent volumes):

```sh
docker compose -f docker-compose.yml -f docker-compose.test.yml --profile test up -d
```

An overlay is used instead of inline profile services because the test variant
*modifies existing services*; duplicating the stack under a profile would
drift. The root Makefile's `test-integration` currently passes only
`--profile test` — it works, but should grow the second `-f` flag to get the
ephemeral behaviour.

## Dev conveniences (host ports)

| URL | What |
|---|---|
| https://localhost | gateway → web / APIs / Keycloak |
| http://localhost:8081 | Keycloak direct (dev only) |
| http://localhost:8025 | Mailpit (all outbound email) |
| http://localhost:9001 | MinIO console |
| http://localhost:3001 | Grafana (`observability` profile) |
| http://localhost:9090 | Prometheus (`observability` profile) |

`fhir`, `postgres`, and `redis` are **never** published — internal network
only (01 §1: nothing reaches HAPI except through the gateway path).

## face-sim (dev stub for the external face service, 05)

```sh
docker compose exec face-sim python /opt/face-sim/sim.py send                  # valid match
docker compose exec face-sim python /opt/face-sim/sim.py send --replay        # stale ts / duplicate id
docker compose exec face-sim python /opt/face-sim/sim.py send --bad-signature # must be rejected
docker compose exec face-sim python /opt/face-sim/sim.py send --count 30      # opening-rush burst
```

## Secrets

Local dev uses harmless `dev-*` defaults (override via `.env`, template
`.env.example`). **No real secrets in any `.env`, ever** — real environments
are SOPS-injected (`infra/secrets/`, 10 §5). The per-service files under
`env/` are optional locally and rendered from SOPS elsewhere.
