# platform/keycloak — Keycloak 26.x, realm-as-code

Identity provider for every human and service principal on the platform.

**Governing document: [docs/solution/02-identity-access-mpi.md](../../docs/solution/02-identity-access-mpi.md)**
(§1 deployment, §2 clients/scopes, §3 role matrix, §4 MFA, §5 ACR/LoA step-up).

## The no-click-ops rule (02 §1, ADR I-1)

The entire realm — clients, roles, client scopes, authentication flows, required
actions, ACR/LoA mapping — is declared in `realm/medagent.yaml` and applied
**idempotently** by [keycloak-config-cli](https://github.com/adorsys/keycloak-config-cli).

- **Hand-edits in the admin console do not persist.** Drift is overwritten on the
  next apply. If you need a realm change, change the YAML and open a PR.
- A CI realm-lint step additionally asserts no role accumulates scopes outside
  the 02 §3 matrix.
- **Secrets never live in the YAML.** `$(env:...)` placeholders are substituted
  by config-cli at apply time (`--import.var-substitution.enabled=true`) from
  vault-injected environment (10 §5): `KC_WEB_CLIENT_SECRET`,
  `KC_KIOSK_DEVICE_CLIENT_SECRET`, `KC_CORE_API_CLIENT_SECRET`,
  `KC_AGENT_SERVICE_CLIENT_SECRET`, `KC_CONFIG_CLI_CLIENT_SECRET`.

## How the import runs

The `Dockerfile` bakes **both** the pinned config-cli jar and `realm/` into the
Keycloak image (10 §1 "config-cli baked realm import") — one artifact carries the
server *and* the realm version, and imports work in air-gapped environments.

The import itself is a **one-shot job container from this same image**, run after
Keycloak reports healthy (management port 9000, `/health/ready`):

```bash
docker run --rm --entrypoint java medagent/keycloak \
  -jar /opt/keycloak-config-cli/keycloak-config-cli.jar \
  --keycloak.url="$KEYCLOAK_URL" \
  --keycloak.user="$KEYCLOAK_USER" --keycloak.password="$KEYCLOAK_PASSWORD" \
  --import.files.locations=/opt/keycloak-config/realm/medagent.yaml \
  --import.var-substitution.enabled=true
```

- **dev (compose):** a `keycloak-config` service runs this on boot
  (`depends_on: keycloak: condition: service_healthy`) and *additionally* imports
  `realm/dev-users.yaml`.
- **staging/pilot (CI, 10 §3.2):** the same command as a deploy step, applying
  **only** `medagent.yaml`. `dev-users.yaml` is never applied beyond dev.
- CI also runs a config-cli **dry-run against a throwaway Keycloak container**
  on every PR touching this directory (10 §3.2).

## Files

```
keycloak/
├── Dockerfile            # quay.io/keycloak/keycloak:26.7 + baked config-cli 6.4.0-26 + realm/
├── realm/
│   ├── medagent.yaml     # THE realm: 11 roles (+ internal `staff` composite), clients,
│   │                     # scopes + audience mappers, ACR/LoA + conditional-TOTP flows
│   └── dev-users.yaml    # DEV ONLY throwaway users (dr_demo, reception_demo, patient_demo)
└── README.md
```

## Design notes (pointers, not duplicates)

- **Single `medagent` realm** for staff + patients (ADR I-2). `master` holds no
  application users; bootstrap admin exists only for config-cli (02 §1).
- **All 11 roles defined day 1**, six pilot-active (doctor, nurse, receptionist,
  admin, patient, guardian) — dormancy is documented per-role in the YAML (02 §3).
- **`break_glass` is a modifier**, not a standing grant: Phase A break-glass is an
  audited manual procedure in core-api `app_db`, deliberately *not* a Keycloak
  role mutation (02 §6, ADR I-4).
- **No face-service client** — HMAC-signed webhook per 05 §3 (locked D5).
- **Audience per service** (`aud:*` client scopes): every resource server rejects
  tokens not minted for it (02 §2).
- **Step-up (loa2, Max Age 300 s)** gates e-prescription sign-off, break-glass
  activation, ward-consent changes and admin changes; the `acr` claim is verified
  server-side at the commit paths, never trusted from the UI (02 §5).
- Keycloak is reachable **only via the gateway `/auth` route**
  (`platform/gateway/dynamic/routes.yaml`); the admin console binds to an
  internal hostname, never exposed publicly (02 §1).
