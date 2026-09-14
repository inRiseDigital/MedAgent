/*
 * shot.mjs — capture a baseline screenshot of a running MedAgent web page,
 * doing the full Keycloak OIDC login first. Plain Node script (no test runner)
 * using Playwright's bundled Chromium. Runs ON THE HOST against the Docker stack.
 *
 * WHY https://localhost (the gateway) and NOT http://localhost:3000:
 *   The web container is wired for the gateway origin — NEXT_PUBLIC_APP_URL is
 *   https://localhost, so the BFF builds redirect_uri=https://localhost/api/auth/
 *   callback and the session cookie is __Host-session (browsers only accept a
 *   __Host- cookie over HTTPS). Hitting :3000 directly sends the OIDC callback to
 *   https://localhost anyway, stranding the session on the wrong origin. The
 *   gateway uses a self-signed cert, so we launch with ignoreHTTPSErrors.
 *
 * USAGE
 *   node e2e/shot.mjs <username> <route> [outName]
 *   USER=dr_demo ROUTE=/queue OUT=queue node e2e/shot.mjs
 *
 * Produces TWO files per run under e2e/shots/:
 *   <outName>-desktop.png  (1440x900 viewport)
 *   <outName>-mobile.png   ( 390x844 viewport)
 *
 * Args (positional take precedence over env):
 *   username   Keycloak username, e.g. dr_demo / patient_demo / reception_demo
 *   route      app path to capture, e.g. /queue  /portal  /patients/<id>
 *   outName    base file name (no extension); defaults to a slug of user+route
 *
 * Env overrides:
 *   BASE_URL   default https://localhost
 *   PASSWORD   default dev-only-<username>   (the dev realm convention)
 *   HEADED=1   run with a visible browser window (debugging)
 *   FULLPAGE=0 capture only the viewport instead of the full scrollable page
 *   TIMEOUT    per-navigation timeout ms (default 45000)
 */
import { chromium } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { dirname, resolve, isAbsolute } from "node:path";
import { mkdir } from "node:fs/promises";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SHOTS_DIR = resolve(__dirname, "shots");

// ── args / config ──────────────────────────────────────────────────────────
const username = process.argv[2] ?? process.env.USER_NAME ?? process.env.USER;
const route = process.argv[3] ?? process.env.ROUTE;
if (!username || !route) {
  console.error("usage: node e2e/shot.mjs <username> <route> [outName]");
  console.error("   or: USER=dr_demo ROUTE=/queue OUT=queue node e2e/shot.mjs");
  process.exit(2);
}
const password = process.env.PASSWORD ?? `dev-only-${username}`;
const baseUrl = (process.env.BASE_URL ?? "https://localhost").replace(/\/$/, "");
const path = route.startsWith("/") ? route : `/${route}`;
const outName =
  process.argv[4] ??
  process.env.OUT ??
  `${username}${path}`.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase();
const fullPage = process.env.FULLPAGE !== "0";
const navTimeout = Number(process.env.TIMEOUT ?? 45000);
const headed = process.env.HEADED === "1" || process.env.HEADED === "true";

const DESKTOP = { name: "desktop", width: 1440, height: 900 };
const MOBILE = { name: "mobile", width: 390, height: 844, isMobile: true, deviceScaleFactor: 2 };

const onAuthServer = (url) => /\/auth\/realms\//.test(url) || /openid-connect\/auth/.test(url);

/** Perform the Keycloak login on `page` if the login form is present. */
async function loginIfNeeded(page) {
  // Give redirects a beat to settle onto either the app or the Keycloak form.
  await page.waitForLoadState("domcontentloaded").catch(() => {});
  const userField = page.locator("#username");
  const hasForm = (await userField.count()) > 0 && (await userField.isVisible().catch(() => false));

  if (!hasForm) {
    if (onAuthServer(page.url())) {
      throw new Error(`On Keycloak (${page.url()}) but no #username field — form/selector changed.`);
    }
    console.log("  already authenticated (no login form shown)");
    return;
  }

  console.log(`  Keycloak login form detected — signing in as ${username}`);
  await userField.fill(username);
  await page.locator("#password").fill(password);
  await Promise.all([
    page.waitForURL((url) => !onAuthServer(url.toString()), { timeout: navTimeout }).catch(() => {}),
    page.locator("#kc-login").click(),
  ]);

  if (onAuthServer(page.url())) {
    // Still on Keycloak: surface the visible error (bad creds, etc.).
    const err = await page
      .locator("#input-error, .kc-feedback-text, .pf-v5-c-alert__title, .alert-error")
      .first()
      .textContent()
      .catch(() => null);
    throw new Error(`Login did not leave Keycloak. Message: ${err?.trim() || "(none shown)"}`);
  }
  console.log(`  login OK -> ${page.url()}`);
}

/** Let the page settle: DOM, best-effort network idle (SSE keeps a conn open,
 *  so networkidle may never fire — bound it), then a short beat for motion. */
async function settle(page) {
  await page.waitForLoadState("domcontentloaded").catch(() => {});
  await page.waitForLoadState("networkidle", { timeout: 6000 }).catch(() => {});
  await page.waitForTimeout(1200);
}

async function main() {
  await mkdir(SHOTS_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: !headed });
  const results = [];
  try {
    // Desktop context does the real login; we reuse its storage for mobile so we
    // don't authenticate twice.
    const desktopCtx = await browser.newContext({
      viewport: { width: DESKTOP.width, height: DESKTOP.height },
      ignoreHTTPSErrors: true,
    });
    const dPage = await desktopCtx.newPage();
    const target = `${baseUrl}${path}`;
    console.log(`\n[${outName}] ${username} -> ${target}`);
    await dPage.goto(target, { waitUntil: "domcontentloaded", timeout: navTimeout });
    await loginIfNeeded(dPage);
    // Ensure we're actually on the requested route (login redirects to returnTo).
    if (new URL(dPage.url()).pathname !== path) {
      await dPage.goto(target, { waitUntil: "domcontentloaded", timeout: navTimeout }).catch(() => {});
    }
    await settle(dPage);
    const dOut = resolve(SHOTS_DIR, `${outName}-desktop.png`);
    await dPage.screenshot({ path: dOut, fullPage });
    results.push([dOut, `landed on ${dPage.url()}`]);
    console.log(`  saved ${dOut}`);

    const storageState = await desktopCtx.storageState();
    await desktopCtx.close();

    // Mobile context reuses the authenticated session — straight to the route.
    const mobileCtx = await browser.newContext({
      viewport: { width: MOBILE.width, height: MOBILE.height },
      isMobile: MOBILE.isMobile,
      deviceScaleFactor: MOBILE.deviceScaleFactor,
      hasTouch: true,
      ignoreHTTPSErrors: true,
      storageState,
    });
    const mPage = await mobileCtx.newPage();
    await mPage.goto(target, { waitUntil: "domcontentloaded", timeout: navTimeout });
    await loginIfNeeded(mPage); // no-op if session carried over
    await settle(mPage);
    const mOut = resolve(SHOTS_DIR, `${outName}-mobile.png`);
    await mPage.screenshot({ path: mOut, fullPage });
    results.push([mOut, `landed on ${mPage.url()}`]);
    console.log(`  saved ${mOut}`);
    await mobileCtx.close();
  } finally {
    await browser.close();
  }
  console.log("\nDONE:");
  for (const [f, note] of results) console.log(`  ${f}  (${note})`);
}

main().catch((err) => {
  console.error("\nFAILED:", err.message);
  process.exit(1);
});
