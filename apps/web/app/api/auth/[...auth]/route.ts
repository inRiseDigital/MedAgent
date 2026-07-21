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
  appUrl,
  buildAuthorizeUrl,
  buildLogoutUrl,
  exchangeCode,
  pkceChallenge,
  randomToken,
} from "@/lib/oidc";
import { SESSION_COOKIE } from "@/lib/session";
import { createSession, destroySession, getSession } from "@/lib/session-store";

// These handlers use node:crypto/redis transitively — force the Node runtime.
export const runtime = "nodejs";

const KNOWN_ACTIONS = ["login", "callback", "logout", "session"] as const;
type AuthAction = (typeof KNOWN_ACTIONS)[number];

// Short-lived httpOnly cookie carrying the OIDC transaction (state, verifier,
// nonce, returnTo) between /login and /callback. Encrypted-at-rest is overkill
// for a 10-min single-use value on an httpOnly Secure cookie.
const TX_COOKIE = "__Host-oidc-tx";
const TX_MAX_AGE = 600;

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

async function handleCallback(request: NextRequest): Promise<NextResponse> {
  const params = request.nextUrl.searchParams;
  const code = params.get("code");
  const state = params.get("state");

  const txRaw = request.cookies.get(TX_COOKIE)?.value;
  if (!code || !state || !txRaw) {
    return NextResponse.json({ error: "invalid_callback" }, { status: 400 });
  }

  let tx: OidcTransaction;
  try {
    tx = JSON.parse(txRaw) as OidcTransaction;
  } catch {
    return NextResponse.json({ error: "invalid_transaction" }, { status: 400 });
  }
  if (tx.state !== state) {
    return NextResponse.json({ error: "state_mismatch" }, { status: 400 });
  }

  let sessionId: string;
  try {
    const tokens = await exchangeCode(code, tx.verifier);
    sessionId = await createSession(tokens);
  } catch {
    return NextResponse.json({ error: "token_exchange_failed" }, { status: 502 });
  }

  // Redirect against the PUBLIC origin (from forwarded headers) — request.url is
  // the container's internal bind (0.0.0.0:3000), which the browser cannot follow.
  const res = NextResponse.redirect(new URL(safeReturnTo(tx.returnTo), publicBase(request)));
  res.cookies.set(SESSION_COOKIE, sessionId, baseCookieOptions());
  res.cookies.delete(TX_COOKIE);
  return res;
}

async function handleLogout(_request: NextRequest): Promise<NextResponse> {
  const idToken = await destroySession();
  const target = idToken ? await buildLogoutUrl(idToken) : appUrl();
  const res = NextResponse.redirect(target);
  res.cookies.delete(SESSION_COOKIE);
  return res;
}

async function handleSession(): Promise<NextResponse> {
  const session = await getSession();
  if (!session) return NextResponse.json({ authenticated: false }, { status: 401 });
  return NextResponse.json({
    authenticated: true,
    displayName: session.displayName,
    roles: session.roles,
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
