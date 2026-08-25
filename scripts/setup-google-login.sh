#!/usr/bin/env bash
# =============================================================================
# Enable "Sign in with Google" on the medagent realm.
#
# Prereq: a Google Cloud OAuth 2.0 *Web application* client. On it, register the
# authorized redirect URI EXACTLY:
#
#     https://localhost/auth/realms/medagent/broker/google/endpoint
#
# Then run:
#     GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com \
#     GOOGLE_CLIENT_SECRET=yyyyy \
#     ./scripts/setup-google-login.sh
#
# Idempotent: creates the provider if missing, updates it if present. Applies
# live via the Keycloak admin API (no full realm re-apply). To make it permanent
# across rebuilds, the same provider is already declared in
# platform/keycloak/realm/medagent.yaml (env-substituted).
# =============================================================================
set -euo pipefail

KC="${KC_URL:-https://localhost/auth}"          # gateway-fronted Keycloak
REALM="medagent"
ADMIN="${KEYCLOAK_ADMIN_USER:-admin}"
ADMIN_PW="${KEYCLOAK_ADMIN_PASSWORD:-dev-admin-pw}"
CID="${GOOGLE_CLIENT_ID:-}"
CSECRET="${GOOGLE_CLIENT_SECRET:-}"
CURL=(curl -sk)   # -k: dev uses a self-signed cert on https://localhost

[ -n "$CID" ] && [ -n "$CSECRET" ] || {
  echo "ERROR: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET." >&2
  echo "Redirect URI to register on the Google client:" >&2
  echo "  ${KC}/realms/${REALM}/broker/google/endpoint" >&2
  exit 1
}

echo "1/3  Getting an admin token…"
ATOK="$("${CURL[@]}" -X POST "${KC}/realms/master/protocol/openid-connect/token" \
  -d grant_type=password -d client_id=admin-cli \
  -d "username=${ADMIN}" -d "password=${ADMIN_PW}" | grep -oE '"access_token":"[^"]+"' | cut -d'"' -f4)"
[ -n "$ATOK" ] || { echo "ERROR: admin login failed (is Keycloak up at ${KC}?)." >&2; exit 1; }

read -r -d '' BODY <<JSON || true
{
  "alias": "google",
  "displayName": "Google",
  "providerId": "google",
  "enabled": true,
  "trustEmail": true,
  "storeToken": false,
  "firstBrokerLoginFlowAlias": "first broker login",
  "config": {
    "clientId": "${CID}",
    "clientSecret": "${CSECRET}",
    "defaultScope": "openid profile email",
    "syncMode": "IMPORT",
    "useJwksUrl": "true"
  }
}
JSON

echo "2/3  Applying the Google identity provider…"
CODE="$("${CURL[@]}" -o /dev/null -w '%{http_code}' -X POST \
  "${KC}/admin/realms/${REALM}/identity-provider/instances" \
  -H "authorization: Bearer ${ATOK}" -H "content-type: application/json" -d "${BODY}")"

if [ "$CODE" = "409" ]; then
  echo "     exists — updating…"
  "${CURL[@]}" -X PUT "${KC}/admin/realms/${REALM}/identity-provider/instances/google" \
    -H "authorization: Bearer ${ATOK}" -H "content-type: application/json" -d "${BODY}"
elif [ "$CODE" != "201" ]; then
  echo "ERROR: create returned HTTP ${CODE}." >&2; exit 1
fi

echo "3/3  Done. 'Sign in with Google' is live at https://localhost"
echo "     (Register this redirect URI on the Google client if you haven't:"
echo "      ${KC}/realms/${REALM}/broker/google/endpoint )"
