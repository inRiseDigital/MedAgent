/*
 * BFF session model — EDGE-SAFE surface only.
 *
 * apps/web is a CONFIDENTIAL OIDC client of Keycloak (Auth Code + PKCE).
 * Access/refresh tokens live in an encrypted server-side record (Redis),
 * keyed by the __Host-session cookie; tokens NEVER reach browser JavaScript
 * (docs/solution/06 §2.1, 02 §4 ADR W-2).
 *
 * This module is imported by proxy.ts, which runs on the edge runtime, so it
 * must stay free of node:crypto / redis. The actual session store (record
 * lookup, decryption, silent refresh) lives in lib/session-store.ts
 * (Node-only, "server-only") and is imported exclusively by route handlers
 * and server components.
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
  /** Patient's own PHN (portal patients only) — from the `phn` token claim (02 §8.5). */
  patientPhn?: string;
}

/**
 * Cheap, edge-compatible presence check used by proxy.ts. UX-grade only:
 * the gateway re-validates the real token on every API call regardless
 * (defence in depth, 06 §2.2).
 */
export function hasSessionCookie(request: NextRequest): boolean {
  return Boolean(request.cookies.get(SESSION_COOKIE)?.value);
}

// Server-side session resolution (record lookup, silent refresh, access-token
// retrieval) lives in lib/session-store.ts — Node-only, never imported here so
// this module stays edge-safe for proxy.ts.
