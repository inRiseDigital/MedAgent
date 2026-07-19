# Synthea seed job

Implements 10-devops-infrastructure.md §2.3. Run with:

```sh
docker compose --profile seed up seed --abort-on-container-exit   # or: make seed
```

## What it does (three steps, in order)

1. **Generate or restore** — produces FHIR R4 transaction bundles for ~1,000
   synthetic, Sri Lanka-adjusted patients using a **pinned Synthea release**
   (`SYNTHEA_VERSION` in `seed.py`, currently `v3.3.0`), or restores a cached,
   versioned bundle set from the `seed_bundles` volume
   (`/bundles/seed-v{n}/*.json`). *S1 status: the Synthea invocation is a
   stub — drop a pre-generated bundle set into the volume, or build the `seed`
   image with the pinned jar (the command shape is in `seed.py`).*
2. **Load via the gateway** — POSTs each transaction bundle to
   `{GATEWAY_URL}/fhir` with an OAuth2 client-credentials service token
   (`seed-job` Keycloak client). This deliberately exercises the HAPI
   authz/consent/audit interceptors; the seed never talks to HAPI directly.
3. **Register in MPI** — registers every patient with core-api's MPI so
   **PHNs are issued through the real MPI issuance path** (03 §7 / ADR F-8),
   never injected post-generation. A deterministic subset carries known PHNs
   for fixtures, and the first ~10 patients are marked as **demo patients**:
   face-consent granted and `ext_face_id` stubs (`demo-face-0001` …
   `demo-face-0010`) so `face-sim` events resolve out of the box:

   ```sh
   docker compose exec face-sim python /opt/face-sim/sim.py send --ext-face-id demo-face-0001
   ```

## Versioning

Seed data is versioned as `seed/v{n}` (`SEED_VERSION` env). Regenerating
bundles (new Synthea pin, changed localisation config) bumps the version;
eval golden cases (04 §6) pin the seed version they were graded against —
never mutate an existing version in place.

## Configuration

| Env | Default | Meaning |
|---|---|---|
| `SEED_VERSION` | `v1` | bundle set under `/bundles/seed-{version}` |
| `GATEWAY_URL` | `https://gateway` | all traffic goes through the gateway |
| `KEYCLOAK_URL` / `KEYCLOAK_REALM` | `http://keycloak:8080` / `medagent` | token endpoint |
| `SEED_CLIENT_ID` / `SEED_CLIENT_SECRET` | `seed-job` / — | service client (secret via `.env` locally, SOPS elsewhere) |
| `SEED_INSECURE_TLS` | unset | `1` in dev only (mkcert CA not in container) |

Never run against anything but Synthea data (10 §2.4).
