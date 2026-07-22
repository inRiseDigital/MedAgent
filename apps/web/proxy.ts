/*
 * proxy.ts — Next 16 name for the request interceptor (formerly
 * middleware.ts; 06 §1 table). S1 scaffold — completed in S2 per
 * docs/solution/02 §4 and 06 §2.2.
 *
 * Responsibilities (target design):
 * 1. Validate the __Host-session cookie against the encrypted server-side
 *    session store (Redis) — tokens never reach the browser (ADR W-2).
 * 2. Enforce role → route-group mapping: doctor|nurse|receptionist →
 *    (doctor)/(kiosk); patient|guardian → (patient-portal). A patient
 *    session can NEVER reach doctor or kiosk routes and vice versa.
 * 3. Redirect unauthenticated requests to /api/auth/login before any page
 *    code runs.
 *
 * This is UX-grade protection; the gateway re-validates the bearer token
 * on every API call regardless (security-grade, 01 §1).
 */
import { NextResponse, type NextRequest } from "next/server";
import { hasSessionCookie } from "@/lib/session";

export default function proxy(request: NextRequest): NextResponse {
  if (!hasSessionCookie(request)) {
    const login = new URL("/api/auth/login", request.url);
    login.searchParams.set("returnTo", request.nextUrl.pathname);
    return NextResponse.redirect(login);
  }
  // S2: validate the session record server-side + map roles to route
  // groups; presence-only checking is a scaffold placeholder.
  return NextResponse.next();
}

export const config = {
  /*
   * Route groups don't appear in URLs, so the (doctor) group is protected
   * by its concrete paths (06 §1): queue, patients, day, proposals.
   * S2 extends the matcher to (patient-portal) and (kiosk) once their
   * session/role models land (07 §2, 05 §5).
   */
  matcher: [
    "/queue/:path*",
    "/patients/:path*",
    "/day/:path*",
    "/proposals/:path*",
    "/portal/:path*",
  ],
};
