/*
 * BFF auth endpoints — S1 scaffold, implemented in S2 per docs/solution/02
 * §4 and 06 §2.2 (ADR W-2). Keycloak OIDC Authorization Code + PKCE as a
 * CONFIDENTIAL client; all token handling is server-side and the browser
 * never holds a token — only the httpOnly __Host-session cookie.
 *
 * Segments handled here:
 *   GET  /api/auth/login     → 302 to Keycloak authorize endpoint
 *                              (code_challenge, state, nonce; returnTo kept
 *                              server-side against open redirects)
 *   GET  /api/auth/callback  → exchange code (client secret + PKCE
 *                              verifier), create encrypted Redis session,
 *                              Set-Cookie: __Host-session (httpOnly,
 *                              Secure, SameSite=Lax), redirect to returnTo
 *   POST /api/auth/logout    → destroy session record, clear cookie,
 *                              Keycloak RP-initiated logout
 *   GET  /api/auth/session   → minimal display claims for the shell
 *                              (name, roles) — NEVER tokens
 *
 * Step-up auth for prescription sign-off (acr_values, 06 §2.2/§7) rides
 * the same handlers in S4.
 */
import { NextResponse, type NextRequest } from "next/server";

const KNOWN_ACTIONS = ["login", "callback", "logout", "session"] as const;
type AuthAction = (typeof KNOWN_ACTIONS)[number];

function notImplemented(action: AuthAction): NextResponse {
  return NextResponse.json(
    {
      error: "not_implemented",
      detail: `auth:${action} is an S1 scaffold — OIDC code flow lands in S2 (docs/solution/02 §4, 06 §2.2)`,
    },
    { status: 501 },
  );
}

function resolveAction(segments: string[]): AuthAction | null {
  const [first] = segments;
  return (KNOWN_ACTIONS as readonly string[]).includes(first ?? "")
    ? (first as AuthAction)
    : null;
}

export async function GET(
  _request: NextRequest,
  context: { params: Promise<{ auth: string[] }> },
): Promise<NextResponse> {
  const { auth } = await context.params;
  const action = resolveAction(auth);
  if (action === null) return NextResponse.json({ error: "not_found" }, { status: 404 });
  if (action === "logout") {
    // Logout must be POST (state-changing; CSRF surface).
    return NextResponse.json({ error: "method_not_allowed" }, { status: 405 });
  }
  return notImplemented(action);
}

export async function POST(
  _request: NextRequest,
  context: { params: Promise<{ auth: string[] }> },
): Promise<NextResponse> {
  const { auth } = await context.params;
  const action = resolveAction(auth);
  if (action !== "logout") return NextResponse.json({ error: "not_found" }, { status: 404 });
  return notImplemented(action);
}
