#!/usr/bin/env python3
"""Dev-only Keycloak bootstrap — applies the few realm settings that
keycloak-config-cli does not reliably apply in this setup (client default-scope
assignments and the dev browser-flow binding). Idempotent; admin REST only;
stdlib only (runs on python:3.12-slim, no deps).

NEVER run against staging/pilot: it binds the realm to the built-in `browser`
flow (frictionless dev login — conditional OTP only challenges enrolled users),
whereas prod keeps `medagent-browser` with provisioning-enforced staff MFA (02).

Env:
  KC_URL   (default http://keycloak:8080/auth)
  KC_REALM (default medagent)
  KC_ADMIN / KC_ADMIN_PASSWORD (default admin / dev-admin-pw)
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

KC_URL = os.environ.get("KC_URL", "http://keycloak:8080/auth").rstrip("/")
REALM = os.environ.get("KC_REALM", "medagent")
ADMIN = os.environ.get("KC_ADMIN", "admin")
ADMIN_PW = os.environ.get("KC_ADMIN_PASSWORD", "dev-admin-pw")

# Standard Keycloak scopes the BFF web client needs so tokens carry realm roles
# etc. (roles -> realm_access.roles). Clinical/aud scopes stay optional (02 §2).
WEB_DEFAULT_SCOPES = ["profile", "email", "roles", "basic", "acr", "web-origins"]
DEV_BROWSER_FLOW = "browser"


def _req(method: str, path: str, token: str | None = None, body: dict | None = None) -> bytes:
    url = f"{KC_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def admin_token() -> str:
    body = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": ADMIN,
            "password": ADMIN_PW,
        }
    ).encode()
    req = urllib.request.Request(
        f"{KC_URL}/realms/master/protocol/openid-connect/token", data=body, method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["access_token"]


def main() -> None:
    tok = admin_token()

    # 1. web client default scopes -----------------------------------------
    # NOTE: Keycloak ignores `defaultClientScopes` on the main client PUT — scope
    # assignments live on a dedicated sub-resource. (This is why config-cli and a
    # naive client PUT both silently fail to apply them.)
    clients = json.loads(_req("GET", f"/admin/realms/{REALM}/clients?clientId=web", tok))
    if not clients:
        raise SystemExit("web client not found — run keycloak-config first")
    web_id = clients[0]["id"]

    all_scopes = json.loads(_req("GET", f"/admin/realms/{REALM}/client-scopes", tok))
    scope_id = {s["name"]: s["id"] for s in all_scopes}
    assigned = {
        s["name"]
        for s in json.loads(_req("GET", f"/admin/realms/{REALM}/clients/{web_id}/default-client-scopes", tok))
    }
    for name in WEB_DEFAULT_SCOPES:
        if name in assigned:
            continue
        sid = scope_id.get(name)
        if not sid:
            print(f"  (skip: no client scope named {name})")
            continue
        _req("PUT", f"/admin/realms/{REALM}/clients/{web_id}/default-client-scopes/{sid}", tok)
        print(f"  web default scope += {name}")
    print("web defaultClientScopes ensured")

    # 1b. dev-cli client (direct grant) — lets dev tooling/tests mint user tokens.
    existing = json.loads(_req("GET", f"/admin/realms/{REALM}/clients?clientId=dev-cli", tok))
    if not existing:
        _req("POST", f"/admin/realms/{REALM}/clients", tok, {
            "clientId": "dev-cli",
            "enabled": True,
            "publicClient": True,
            "directAccessGrantsEnabled": True,
            "standardFlowEnabled": False,
        })
        print("created dev-cli client (direct grant, dev only)")
    else:
        print("dev-cli client already present")

    # 2. dev browser flow ---------------------------------------------------
    realm = json.loads(_req("GET", f"/admin/realms/{REALM}", tok))
    if realm.get("browserFlow") != DEV_BROWSER_FLOW:
        realm["browserFlow"] = DEV_BROWSER_FLOW
        _req("PUT", f"/admin/realms/{REALM}", tok, realm)
        print(f"realm browserFlow -> {DEV_BROWSER_FLOW}")
    else:
        print("realm browserFlow already set")

    print("dev bootstrap complete")


if __name__ == "__main__":
    main()
