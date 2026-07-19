/*
 * S1 scaffold — BFF session model stub, completed in S2 per
 * docs/solution/02 §4 and 06 §2.2 (ADR W-2).
 *
 * Design being implemented:
 * - apps/web is a CONFIDENTIAL OIDC client of Keycloak (Auth Code + PKCE).
 * - Access/refresh tokens live in an ENCRYPTED SERVER-SIDE session record
 *   (Redis-backed, SESSION_REDIS_URL), keyed by the __Host-session cookie.
 *   Tokens NEVER reach browser JavaScript — the prototype's localStorage
 *   model is explicitly rejected (06 §2.1).
 * - Silent refresh happens server-side from the session's refresh token;
 *   idle/max lifetimes follow Keycloak SSO settings (12 h max, 30 min idle
 *   for doctor roles — 02).
 *
 * This module stays edge-safe: proxy.ts imports the cookie name and the
 * cheap presence check; full validation (Redis lookup, expiry, roles) is
 * S2 work and runs here + in route handlers.
 */
import type { NextRequest } from "next/server";

/**
 * __Host- prefix: Secure, no Domain, Path=/ — the cookie cannot be set by
 * subdomains or over plain HTTP. localhost counts as a secure context in
 * modern browsers, so this works in dev too.
 */
export const SESSION_COOKIE = "__Host-session";

export type Role =
  | "doctor"
  | "nurse"
  | "receptionist"
  | "admin"
  | "patient"
  | "guardian";

export interface Session {
  /** Keycloak subject. */
  sub: string;
  /** Realm roles — drives route-group authorisation in proxy.ts (06 §2.2). */
  roles: Role[];
  displayName: string;
}

/**
 * Cheap, edge-compatible presence check used by proxy.ts. UX-grade only:
 * the gateway re-validates the real token on every API call regardless
 * (defence in depth, 06 §2.2).
 */
export function hasSessionCookie(request: NextRequest): boolean {
  return Boolean(request.cookies.get(SESSION_COOKIE)?.value);
}

/**
 * Resolve and validate the server-side session record for this request.
 * S2: look up the cookie value in Redis, decrypt, check expiry, refresh
 * the access token if stale, return roles for route-group mapping.
 */
export async function getSession(): Promise<Session | null> {
  // S1 scaffold — no session store yet; every caller must treat null as
  // "unauthenticated" (implemented in S2 per docs/solution/11).
  return null;
}

/**
 * S2: return the session's current access token for server-side attachment
 * to ts-sdk calls (BFF pattern — the browser never sees it).
 */
export async function getAccessToken(): Promise<string | null> {
  return null;
}
