/*
 * BFF auth endpoints — Keycloak OIDC Authorization Code + PKCE as a
 * CONFIDENTIAL client (docs/solution/02 §4, 06 §2.2 ADR W-2). All token
 * handling is server-side; the browser only ever holds the httpOnly
 * __Host-session cookie.
 *
 *   GET  /api/auth/login     -> 302 to Keycloak authorize (PKCE, state, nonce)
 *   GET  /api/auth/callback  -> code exchange, create encrypted session,
 *                               Set-Cookie __Host-session, redirect to returnTo
 *   POST /api/auth/logout    -> destroy session, clear cookie, RP-initiated
 *                               logout at Keycloak
 *   GET  /api/auth/session   -> minimal display claims for the shell (never tokens)
 *
 * Step-up auth for prescription sign-off (acr_values, 06 §2.2/§7) reuses the
 * login handler with an acr parameter in S4.
 */
import { NextResponse, type NextRequest } from "next/server";

import {
  buildAuthorizeUrl,
  exchangeCode,
  pkceChallenge,
  randomToken,
} from "@/lib/oidc";
import { SESSION_COOKIE } from "@/lib/session";
import { createSession, destroySession, getAccessToken, getSession } from "@/lib/session-store";

// These handlers use node:crypto/redis transitively — force the Node runtime.
export const runtime = "nodejs";

const KNOWN_ACTIONS = ["login", "callback", "logout", "session"] as const;
type AuthAction = (typeof KNOWN_ACTIONS)[number];

// Short-lived httpOnly cookie carrying the OIDC transaction (state, verifier,
// nonce, returnTo) between /login and /callback. Encrypted-at-rest is overkill
// for a 10-min single-use value on an httpOnly Secure cookie.
const TX_COOKIE = "__Host-oidc-tx";
const TX_MAX_AGE = 600;
// One-shot guard so a genuinely broken callback (e.g. cookies blocked) can't
// bounce forever between /callback and /login.
const RETRY_COOKIE = "__Host-oidc-retry";

interface OidcTransaction {
  state: string;
  nonce: string;
  verifier: string;
  returnTo: string;
}

function baseCookieOptions() {
  return { httpOnly: true, secure: true, sameSite: "lax" as const, path: "/" };
}

/** Only allow same-site path redirects — never an attacker-supplied absolute URL. */
function safeReturnTo(raw: string | null): string {
  if (raw && raw.startsWith("/") && !raw.startsWith("//")) return raw;
  return "/queue";
}

/** Public origin from the gateway's forwarded headers — request.url is the
 *  container's internal bind (0.0.0.0:3000), which the browser cannot follow. */
function publicBase(request: NextRequest): string {
  const proto = request.headers.get("x-forwarded-proto") ?? "https";
  const host =
    request.headers.get("x-forwarded-host") ?? request.headers.get("host") ?? "localhost";
  return `${proto}://${host}`;
}

function resolveAction(segments: string[]): AuthAction | null {
  const [first] = segments;
  return (KNOWN_ACTIONS as readonly string[]).includes(first ?? "")
    ? (first as AuthAction)
    : null;
}

async function handleLogin(request: NextRequest): Promise<NextResponse> {
  const state = randomToken();
  const nonce = randomToken();
  const verifier = randomToken(48);
  const returnTo = safeReturnTo(request.nextUrl.searchParams.get("returnTo"));

  const authorizeUrl = await buildAuthorizeUrl({
    state,
    nonce,
    codeChallenge: pkceChallenge(verifier),
  });

  const tx: OidcTransaction = { state, nonce, verifier, returnTo };
  const res = NextResponse.redirect(authorizeUrl);
  res.cookies.set(TX_COOKIE, JSON.stringify(tx), { ...baseCookieOptions(), maxAge: TX_MAX_AGE });
  return res;
}

/**
 * Recover from a callback that can't complete because the OIDC transaction is
 * stale — the tx cookie expired (login page sat > 10 min / wrong-password
 * fumbling), was never sent, or Keycloak bounced an already-active SSO session
 * without a code. Instead of a dead-end JSON error, restart /login: a fresh
 * transaction is minted and, if an SSO session exists, it completes silently.
 * A one-shot retry cookie stops this looping if cookies are genuinely broken.
 */
function restartLogin(request: NextRequest): NextResponse {
  if (request.cookies.get(RETRY_COOKIE)?.value) {
    const res = NextResponse.json(
      { error: "login_failed", hint: "Please close this tab and open the app again." },
      { status: 400 },
    );
    res.cookies.delete(RETRY_COOKIE);
    res.cookies.delete(TX_COOKIE);
    return res;
  }
  const res = NextResponse.redirect(new URL("/api/auth/login", publicBase(request)));
  res.cookies.set(RETRY_COOKIE, "1", { ...baseCookieOptions(), maxAge: 120 });
  res.cookies.delete(TX_COOKIE);
  return res;
}

async function handleCallback(request: NextRequest): Promise<NextResponse> {
  const params = request.nextUrl.searchParams;
  const code = params.get("code");
  const state = params.get("state");
  const txRaw = request.cookies.get(TX_COOKIE)?.value;

  // Recoverable staleness (or an OIDC error redirect) — restart cleanly.
  if (params.get("error") || !code || !state || !txRaw) {
    return restartLogin(request);
  }

  let tx: OidcTransaction;
  try {
    tx = JSON.parse(txRaw) as OidcTransaction;
  } catch {
    return restartLogin(request);
  }
  if (tx.state !== state) {
    return restartLogin(request);
  }

  let sessionId: string;
  try {
    const tokens = await exchangeCode(code, tx.verifier);
    sessionId = await createSession(tokens);
  } catch {
    // A one-time auth-code is single-use and short-lived; a failed exchange is
    // usually a replayed/expired code, so restart rather than dead-end.
    return restartLogin(request);
  }

  // Redirect against the PUBLIC origin (from forwarded headers) — request.url is
  // the container's internal bind (0.0.0.0:3000), which the browser cannot follow.
  const res = NextResponse.redirect(new URL(safeReturnTo(tx.returnTo), publicBase(request)));
  res.cookies.set(SESSION_COOKIE, sessionId, baseCookieOptions());
  res.cookies.delete(TX_COOKIE);
  res.cookies.delete(RETRY_COOKIE);
  return res;
}

async function handleLogout(request: NextRequest): Promise<NextResponse> {
  // Refresh first so the refresh_token used for the back-channel logout is
  // current (a rotated/expired one would fail to terminate the session).
  try {
    await getAccessToken();
  } catch {
    /* refresh unavailable — destroySession is still best-effort below */
  }
  // destroySession terminates the Keycloak SSO session over the BACK CHANNEL and
  // deletes the local record. We deliberately do NOT redirect the browser to
  // Keycloak's end_session endpoint: Keycloak 26 shows a "Do you want to log
  // out?" consent page for a browser-initiated logout even with a valid
  // id_token_hint, which strands the user instead of returning them to login.
  await destroySession();
  // The Keycloak session is already gone, so /api/auth/login → authorize renders
  // the login page rather than silently re-authenticating. (Going to "/" is
  // unreliable in dev — the root redirect degrades to a 1s meta-refresh.)
  // 303 See Other: this handler runs for a POST (the sign-out form), and the
  // default 307 preserves the method — the browser would POST /api/auth/login,
  // which is GET-only (404). 303 forces the follow-up to be a GET.
  const res = NextResponse.redirect(`${publicBase(request)}/api/auth/login`, 303);
  // Expire the cookie with the SAME attributes — a __Host- cookie only clears
  // when the deletion also carries Secure + Path=/ (a bare delete may not).
  res.cookies.set(SESSION_COOKIE, "", { ...baseCookieOptions(), maxAge: 0 });
  return res;
}

async function handleSession(): Promise<NextResponse> {
  // Liveness check, not just "cookie present": getAccessToken attempts a silent
  // refresh and returns null (clearing the dead session) if the tokens are truly
  // expired. The client SessionGuard polls this to force a clean re-login.
  const token = await getAccessToken();
  const session = token ? await getSession() : null;
  if (!session) return NextResponse.json({ authenticated: false }, { status: 401 });
  return NextResponse.json({
    authenticated: true,
    displayName: session.displayName,
    roles: session.roles,
    patientPhn: session.patientPhn ?? null,
  });
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ auth: string[] }> },
): Promise<NextResponse> {
  const { auth } = await context.params;
  const action = resolveAction(auth);
  if (action === null) return NextResponse.json({ error: "not_found" }, { status: 404 });

  switch (action) {
    case "login":
      return handleLogin(request);
    case "callback":
      return handleCallback(request);
    case "session":
      return handleSession();
    case "logout":
      // Logout is state-changing — must be POST (CSRF surface).
      return NextResponse.json({ error: "method_not_allowed" }, { status: 405 });
  }
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ auth: string[] }> },
): Promise<NextResponse> {
  const { auth } = await context.params;
  const action = resolveAction(auth);
  if (action !== "logout") return NextResponse.json({ error: "not_found" }, { status: 404 });
  return handleLogout(request);
}
