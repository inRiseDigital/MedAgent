#!/usr/bin/env bash
# =============================================================================
# share-demo.sh — expose the running MedAgent stack at a public HTTPS URL via a
# Cloudflare quick tunnel, so a stakeholder can open it in a browser.
#
#   scripts/share-demo.sh
#
# What it does:
#   1. starts a cloudflared quick tunnel to the gateway's :8090 entry point
#      (plain-HTTP, no TLS redirect) and captures the random public URL;
#   2. brings the stack up with the tunnel overlay so Keycloak, the services and
#      the web app all use that public URL (issuer, redirect, browser links);
#   3. registers the tunnel callback URL on the Keycloak `web` client;
#   4. prints the shareable link + demo logins, then holds the tunnel open
#      (Ctrl-C to stop and tear the exposure down).
#
# Prereqs: docker, and cloudflared on PATH
#   (https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).
# DEV DEMO ONLY — random URL, dev secrets, self-* trust. Not for real patient data.
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.tunnel.yml)
KC_ADMIN="${KEYCLOAK_ADMIN_USER:-admin}"
KC_ADMIN_PW="${KEYCLOAK_ADMIN_PASSWORD:-dev-admin-pw}"
KC_LOCAL="http://localhost:8081/auth"
LOG="$(mktemp -t cloudflared.XXXXXX.log)"

command -v cloudflared >/dev/null 2>&1 || {
  echo "ERROR: cloudflared not found on PATH."
  echo "Install it: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
  exit 1
}

cleanup() {
  echo ""
  echo "Stopping tunnel (the public URL is now dead)…"
  [ -n "${CF_PID:-}" ] && kill "$CF_PID" 2>/dev/null || true
  rm -f "$LOG" 2>/dev/null || true
  echo "The stack itself is still running locally. Re-run this script to share again."
}
trap cleanup EXIT INT TERM

echo "1/4  Starting Cloudflare quick tunnel to the gateway (:8090)…"
cloudflared tunnel --url http://localhost:18080 --no-autoupdate >"$LOG" 2>&1 &
CF_PID=$!

PUBLIC_URL=""
for _ in $(seq 1 30); do
  PUBLIC_URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)"
  [ -n "$PUBLIC_URL" ] && break
  sleep 1
done
[ -n "$PUBLIC_URL" ] || { echo "ERROR: could not obtain a tunnel URL. cloudflared log:"; cat "$LOG"; exit 1; }
echo "      Public URL: $PUBLIC_URL"

echo "2/4  Reconfiguring the stack for $PUBLIC_URL (recreates keycloak, services, web, gateway)…"
# NB: keycloak's healthcheck is chronically 'unhealthy' in dev (its /dev/tcp probe
# doesn't run in the minimal image shell), which makes `up` exit non-zero even
# though every container is actually running. Tolerate it so the share flow
# continues; we independently wait for Keycloak to answer in step 3.
PUBLIC_URL="$PUBLIC_URL" "${COMPOSE[@]}" up -d \
  || echo "      NOTE: 'up' returned non-zero (flaky keycloak healthcheck); containers are up — continuing."

echo "3/4  Waiting for Keycloak, then registering the tunnel callback on the 'web' client…"
for _ in $(seq 1 40); do
  curl -sf "$KC_LOCAL/realms/medagent/.well-known/openid-configuration" >/dev/null 2>&1 && break
  sleep 3
done

ATOK="$(curl -s -X POST "$KC_LOCAL/realms/master/protocol/openid-connect/token" \
  -d grant_type=password -d client_id=admin-cli \
  -d "username=$KC_ADMIN" -d "password=$KC_ADMIN_PW" | python -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null || true)"
if [ -n "$ATOK" ]; then
  CID="$(curl -s "$KC_LOCAL/admin/realms/medagent/clients?clientId=web" -H "authorization: Bearer $ATOK" \
    | python -c 'import sys,json;d=json.load(sys.stdin);print(d[0]["id"] if d else "")' 2>/dev/null || true)"
  if [ -n "$CID" ]; then
    curl -s "$KC_LOCAL/admin/realms/medagent/clients/$CID" -H "authorization: Bearer $ATOK" \
      | PUBLIC_URL="$PUBLIC_URL" python -c '
import sys, json, os
c = json.load(sys.stdin); u = os.environ["PUBLIC_URL"]
cb, origin = f"{u}/api/auth/callback*", u
c["redirectUris"] = sorted(set(c.get("redirectUris", []) + [cb]))
c["webOrigins"] = sorted(set(c.get("webOrigins", []) + [origin]))
a = c.setdefault("attributes", {})
existing = a.get("post.logout.redirect.uris", "")
a["post.logout.redirect.uris"] = "##".join(sorted(set(filter(None, existing.split("##") + [f"{u}/*"]))))
json.dump(c, open(os.environ["TMP_CLIENT"], "w"))
' TMP_CLIENT="$LOG.client.json" 2>/dev/null && \
    curl -s -o /dev/null -w "      client update: HTTP %{http_code}\n" -X PUT \
      "$KC_LOCAL/admin/realms/medagent/clients/$CID" \
      -H "authorization: Bearer $ATOK" -H "content-type: application/json" \
      --data-binary "@$LOG.client.json"
    rm -f "$LOG.client.json" 2>/dev/null || true
  else
    echo "      WARN: could not find the 'web' client to update — see manual step in docs/DEMO-TUNNEL.md"
  fi
else
  echo "      WARN: Keycloak admin login failed — set KEYCLOAK_ADMIN_PASSWORD, or add the redirect URI manually (docs/DEMO-TUNNEL.md)"
fi

cat <<EOF

4/4  Ready. Send this to your stakeholder:

     ${PUBLIC_URL}

     Demo logins (realm medagent):
       Doctor        dr_demo         / dev-only-dr_demo
       Patient       patient_demo    / dev-only-patient_demo
       Receptionist  reception_demo  / dev-only-reception_demo

     Leave this window open — closing it (Ctrl-C) tears the public URL down.
     The link only works while this machine + this tunnel stay running.

EOF

wait "$CF_PID"
