# platform/keycloak — Keycloak 26.x with baked keycloak-config-cli realm import
#
# Per docs/solution/02-identity-access-mpi.md §1 (ADR I-1) and 10 §1/§2.1:
# official image, custom layer only for theme + health probes + realm-as-code.
#
# Approach (documented decision): the realm YAML AND the keycloak-config-cli jar
# are BAKED into this image ("config-cli baked realm import", 10 §1). The import
# runs as a one-shot job container from this same image (command: `import`) after
# Keycloak reports healthy — compose/IaC wire that ordering. Baking (vs. a
# separately-pulled sidecar image) keeps realm-version and server-version pinned
# together in one artifact and keeps the import runnable in air-gapped/pilot
# environments. Secrets are NOT in the YAML: config-cli substitutes $(env:...)
# at apply time from the vault-injected environment (02 §1, 10 §5).

# --- config-cli jar source (pinned; compatibility line must match KC major) ---
FROM adorsys/keycloak-config-cli:6.4.0-26 AS config-cli

# --- optimised Keycloak build stage (kc.sh build baked-in features) -----------
FROM quay.io/keycloak/keycloak:26.7 AS builder
ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_HTTP_RELATIVE_PATH=/auth
RUN /opt/keycloak/bin/kc.sh build

# --- runtime -------------------------------------------------------------------
FROM quay.io/keycloak/keycloak:26.7
COPY --from=builder /opt/keycloak/ /opt/keycloak/

# Baked realm-as-code + config-cli (02 §1: no hand-edits in the admin console
# persist; drift is overwritten on the next apply).
COPY --from=config-cli /app/keycloak-config-cli.jar /opt/keycloak-config-cli/keycloak-config-cli.jar
COPY realm/ /opt/keycloak-config/realm/

# Custom theme layer (02 §1) — directory added in S2; keep the mount point stable.
# COPY theme/ /opt/keycloak/themes/medagent/

ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_HTTP_RELATIVE_PATH=/auth \
    KC_PROXY_HEADERS=xforwarded \
    KC_HTTP_ENABLED=true
# Runtime env expected (injected at deploy, never baked — 10 §5):
#   KC_DB_URL / KC_DB_USERNAME / KC_DB_PASSWORD   (dedicated `keycloak` DB, 02 §1)
#   KC_BOOTSTRAP_ADMIN_USERNAME / KC_BOOTSTRAP_ADMIN_PASSWORD (bootstrap only —
#     exists solely for keycloak-config-cli's service account, 02 §1)
#   KC_HOSTNAME (public https://<host>/auth via the gateway; admin console bound
#     to an internal hostname, never exposed publicly — 02 §1)
# Import-job env (when run with the import command):
#   KEYCLOAK_URL / KEYCLOAK_USER / KEYCLOAK_PASSWORD
#   KC_WEB_CLIENT_SECRET, KC_KIOSK_CLIENT_SECRET, ... ($(env:...) substitution)

# Official image already runs as uid 1000 (non-root, 10 §1); declared explicitly.
USER 1000

# Health probes: Keycloak 26 serves /health/{live,ready} on the management port 9000.
EXPOSE 8080 9000

ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start"]

# One-shot realm import (compose service `keycloak-config` / CI step, 10 §3.2):
#   docker run --rm --entrypoint java <this-image> \
#     -jar /opt/keycloak-config-cli/keycloak-config-cli.jar \
#     --keycloak.url=$KEYCLOAK_URL \
#     --keycloak.user=$KEYCLOAK_USER --keycloak.password=$KEYCLOAK_PASSWORD \
#     --import.files.locations=/opt/keycloak-config/realm/medagent.yaml \
#     --import.var-substitution.enabled=true
# Dev adds:  --import.files.locations=/opt/keycloak-config/realm/dev-users.yaml
# (dev-users.yaml is NEVER applied in staging/pilot — see realm/dev-users.yaml)
