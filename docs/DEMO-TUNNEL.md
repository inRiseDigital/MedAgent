# Sharing a live demo over a public tunnel

Expose the **running local stack** at a temporary public HTTPS URL so someone
off your machine (e.g. a stakeholder) can open it in a browser. Nothing is
deployed anywhere — the tunnel just forwards to the gateway on your machine.

> **Dev demo only.** Random URL, dev logins, dev secrets. Never put real patient
> data behind this. The link is alive only while your machine + the tunnel run.
> For a persistent, real deployment use a domain + certs + the per-environment
> route overlay (10 §4), not a tunnel.

## Why it's not "just a static frontend"

The web app is a **BFF** (backend-for-frontend): it runs server-side, holds the
encrypted login session, and proxies to Keycloak / core-api / agent-service /
HAPI. There is no static bundle to hand over — the whole Docker stack must be
running and reachable. This tunnel makes *your* running stack reachable.

## One command

Prereq: **cloudflared** on your PATH — <https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/>
(on Windows: `winget install --id Cloudflare.cloudflared`).

```sh
# stack already up (docker compose ... up -d); then:
bash scripts/share-demo.sh
```

It prints a link like `https://three-random-words.trycloudflare.com`. Send that.
Keep the window open — Ctrl-C tears the public URL down (the local stack keeps
running). Demo logins are printed by the script (doctor `dr_demo` /
`dev-only-dr_demo`, etc.).

## What it changes (and why)

The base stack is wired to `https://localhost`; a visitor's browser can't use
that. The `docker-compose.tunnel.yml` overlay repoints, for the tunnel URL only:

| Piece | localhost | tunnel |
|-------|-----------|--------|
| Keycloak `KC_HOSTNAME` (authorize + token `iss`) | `https://localhost/auth` | `${PUBLIC_URL}/auth` |
| Services' `KEYCLOAK_ISSUER` (token validation) | `https://localhost/…` | `${PUBLIC_URL}/…` |
| Web `NEXT_PUBLIC_*` + issuer (browser links, callback) | `https://localhost…` | `${PUBLIC_URL}…` |
| Gateway entry point | `:443` TLS (Host `localhost`) | `:8090` plain HTTP, host-agnostic (TLS is terminated at the tunnel edge) |

The script also registers `${PUBLIC_URL}/api/auth/callback` on the Keycloak
`web` client so the login redirect is accepted.

## Manual / alternative (ngrok, or a stable URL)

Any tunnel works — point it at the gateway's `:8090` entry point and pass its
URL as `PUBLIC_URL`:

```sh
# terminal 1 — a tunnel to :8090 (example: ngrok)
ngrok http 8090            # or: cloudflared tunnel --url http://localhost:8090

# terminal 2 — bring the stack up for that URL (no trailing slash)
PUBLIC_URL=https://<your-tunnel-host> \
  docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.tunnel.yml up -d
```

Then add `https://<your-tunnel-host>/api/auth/callback*` to the `web` client's
redirect URIs (Keycloak admin at `http://localhost:8081/auth`, realm `medagent`,
client `web`) — or just run `scripts/share-demo.sh`, which does it for you.

**Stable link:** a random `trycloudflare.com` URL changes every run. For a URL
that survives restarts, use an ngrok reserved domain or a named Cloudflare
tunnel and pass it as `PUBLIC_URL` — everything else is identical.

## Back to normal

Stop the tunnel (Ctrl-C in the script window), then return the stack to its
localhost wiring:

```sh
docker compose -f infra/compose/docker-compose.yml up -d
```
