# e2e — see the running UI

`shot.mjs` logs in through Keycloak and screenshots any app page at **desktop
(1440×900)** and **mobile (390×844)** viewports. It's a plain Node + Playwright
script (no test runner) meant to be run **on the host** against the Docker stack,
so you (and the team) can eyeball what the app actually renders.

## Prerequisites

1. **Stack running** in Docker (`infra/compose`) — web, gateway, Keycloak,
   core-api, etc. The gateway must be up because the app is wired to the gateway
   origin (see "Which URL" below).
2. **Chromium downloaded** once for Playwright:
   ```bash
   pnpm -C apps/web shot:setup      # == playwright install chromium
   ```

## Which URL / why HTTPS

The web container is configured for the **gateway origin `https://localhost`**
(`NEXT_PUBLIC_APP_URL=https://localhost`), so:

- the OIDC `redirect_uri` is `https://localhost/api/auth/callback`, and
- the session cookie is `__Host-session`, which browsers only accept over HTTPS.

Hitting `http://localhost:3000` directly does **not** work for login — the OIDC
callback still lands on `https://localhost`, stranding the session on the wrong
origin. So `shot.mjs` defaults to `BASE_URL=https://localhost` and launches with
`ignoreHTTPSErrors: true` (the gateway uses a self-signed dev cert).

## Usage

```bash
# from repo root
pnpm -C apps/web shot:portal      # patient_demo -> /portal
pnpm -C apps/web shot:queue       # dr_demo      -> /queue
pnpm -C apps/web shot:dashboard   # dr_demo      -> /dashboard

# any route (positional: <username> <route> [outName])
pnpm -C apps/web shot dr_demo /referrals referrals

# or with env vars
USER_NAME=patient_demo ROUTE=/portal OUT=portal node apps/web/e2e/shot.mjs
```

Output → `apps/web/e2e/shots/<outName>-desktop.png` and `-mobile.png`.

### Dev users (Keycloak realm `medagent`)

| username         | role    | lands on   |
| ---------------- | ------- | ---------- |
| `dr_demo`        | doctor  | `/queue`   |
| `patient_demo`   | patient | `/portal`  |
| `reception_demo` | staff   | `/queue`   |

Password convention: `dev-only-<username>` (e.g. `dev-only-dr_demo`). Override
with the `PASSWORD` env var.

### Env overrides

| var        | default            | notes                                       |
| ---------- | ------------------ | ------------------------------------------- |
| `BASE_URL` | `https://localhost`| the gateway origin                          |
| `PASSWORD` | `dev-only-<user>`  | Keycloak password                           |
| `FULLPAGE` | `1`                | `0` = capture only the viewport             |
| `HEADED`   | `0`                | `1` = show the browser window (debugging)   |
| `TIMEOUT`  | `45000`            | per-navigation timeout (ms)                 |

## Gotchas

- **Git Bash path mangling (Windows):** a positional route starting with `/`
  (e.g. `/queue`) gets rewritten to a Windows path by MSYS. Run the `pnpm shot:*`
  scripts (safe), or prefix the direct call with `MSYS_NO_PATHCONV=1`, or pass the
  route via the `ROUTE` env var. PowerShell/cmd are unaffected.
- **Patient cockpit (`/patients/<phn>`)** needs a real PHN. The `/patients` page
  is search-by-PHN; queue rows are not links. Full PHNs are patient PII, so
  they're intentionally not dumped here — search for one manually if you need a
  cockpit shot.
- **`networkidle` never fires:** the app holds an SSE (notify) stream open, so
  the script uses a bounded wait plus a short settle delay instead.
- The small dark **“N” circle** in shots is Next.js's dev-mode indicator overlay,
  not part of the UI.
