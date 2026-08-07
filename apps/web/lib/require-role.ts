/*
 * Server-side role gate (06 §2.2). proxy.ts gives UX-grade presence checks at the
 * edge; this gives role-grade checks in server components (it can read the
 * encrypted session record, which the edge middleware cannot). The gateway
 * re-validates the bearer token on every API call regardless (security-grade).
 *
 * Use in a route-group layout (broad gate) or at the top of a page (fine gate).
 * A signed-in user lacking the required role is redirected to a role-appropriate
 * home rather than shown a page they may not use.
 */
import "server-only";

import { redirect } from "next/navigation";

import type { Role, Session } from "@/lib/session";
import { getSession } from "@/lib/session-store";

export const STAFF: Role[] = ["doctor", "nurse", "admin", "receptionist"];
export const CLINICAL: Role[] = ["doctor", "nurse", "admin"];
export const PATIENT: Role[] = ["patient", "guardian"];

/** Home route for a session's primary role — where to bounce on a role mismatch.
 * A signed-in user with NO recognised role must go to a neutral, ungated page,
 * never into a role-gated route (which would bounce them straight back → loop). */
export function homeFor(roles: Role[]): string {
  if (roles.some((r) => PATIENT.includes(r))) return "/portal";
  if (roles.some((r) => STAFF.includes(r))) return "/queue";
  return "/no-access";
}

/**
 * Require the session to hold at least one of `allowed`. Redirects to login if
 * unauthenticated, or to a role-appropriate home if authenticated but not
 * permitted. Returns the Session for the caller to use.
 */
export async function requireRoles(allowed: Role[]): Promise<Session> {
  const session = await getSession();
  if (!session) {
    redirect("/api/auth/login");
  }
  if (!session.roles.some((r) => allowed.includes(r))) {
    redirect(homeFor(session.roles));
  }
  return session;
}
