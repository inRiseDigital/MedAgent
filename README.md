# MedAgent Platform

National-scale AI medical agent platform (Sri Lanka, pilot-first). A monorepo of independently deployable services around a HAPI FHIR R4 clinical core, with a LangGraph clinical agent layer, Keycloak identity, and an external face-recognition check-in integration.

**Design set:** [docs/solution/](docs/solution/) — 22 documents; start at [00-master-plan.md](docs/solution/00-master-plan.md). The sprint plan is [11-sprint-plan-phase-a.md](docs/solution/11-sprint-plan-phase-a.md).

## Layout (01 §2)

| Path | What |
|---|---|
| `apps/web` | Next.js 16 — doctor workspace, patient portal, kiosk route group |
| `services/core-api` | FastAPI — BFF, MPI + PHN issuance, queue, scheduling, consent/audit write paths |
| `services/agent-service` | FastAPI + LangGraph — clinical orchestrator + specialist agents |
| `services/notify-service` | FastAPI — SSE fan-out over Redis pub/sub, SMS/push adapters |
| `platform/fhir` | HAPI FHIR JPA 8.10.x image + authz/consent/audit interceptors (Java) |
| `platform/keycloak` | Realm-as-code (keycloak-config-cli) |
| `platform/gateway` | Traefik dynamic config |
| `packages/ts-sdk` | OpenAPI-generated TS clients (regenerated in CI, never hand-written) |
| `packages/ui` | Design system (see docs/solution/06) |
| `infra/` | compose stack, IaC, CI workflows, perf (k6), observability provisioning |

## Quick start

```bash
docker compose -f infra/compose/docker-compose.yml up      # full local stack
docker compose -f infra/compose/docker-compose.yml --profile seed up seed   # Synthea seed (~1,000 patients)
```

Gateway entry: `https://localhost` (mkcert). HAPI FHIR is network-isolated — reachable only through the gateway with a validated token.

## Rules that are enforced, not advisory

- No secrets in `.env` — gitleaks + push protection; SOPS+age is the vault (10 §5).
- `app_db` schema changes via Alembic only; `hapi_db` belongs to HAPI (10 §9).
- Agent prompt/tool/graph/dataset changes trigger the AI eval gate; regressions block merge (04 §6).
- No PHI in logs or span attributes (10 §6.1).
- Biometric data never enters this platform — the face service is external by contract (05).
