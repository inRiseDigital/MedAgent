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
  // Edge layer does presence-only (it can't read the encrypted session record).
  // Role → route-group enforcement now lives in the server-component layouts/pages
  // via lib/require-role.ts (STAFF for (doctor), CLINICAL for clinical pages,
  // PATIENT for (patient-portal)), and the gateway re-validates the bearer token
  // on every API call (01 §1).
  //
  // i18n scope: the patient portal honours the NEXT_LOCALE switch (Si/Ta/En); the
  // clinician workspace is standardised to English. Tag the request so the
  // next-intl config (i18n/request.ts) only applies the cookie under /portal.
  const headers = new Headers(request.headers);
  headers.set("x-mh-i18n", request.nextUrl.pathname.startsWith("/portal") ? "patient" : "clinician");
  return NextResponse.next({ request: { headers } });
}

export const config = {
  /*
   * Route groups don't appear in URLs, so the (doctor) group is protected
   * by its concrete paths (06 §1): queue, patients, day, proposals, dashboard.
   * S2 extends the matcher to (patient-portal) and (kiosk) once their
   * session/role models land (07 §2, 05 §5).
   */
  matcher: [
    "/queue/:path*",
    "/patients/:path*",
    "/day/:path*",
    "/proposals/:path*",
    "/referrals/:path*",
    "/dashboard/:path*",
    "/portal/:path*",
  ],
};
