/*
 * BFF proposals proxy (06 §7). The workspace posts a proposal here
 * (cookie-authenticated); this attaches the session access token server-side and
 * forwards to core-api's write-back endpoints. `action` is `prescreen` (verdict
 * preview) or `commit` (safety-gated write + audit). core-api re-screens
 * prescriptions itself — this is a transport, not the safety boundary.
 */
import { NextResponse, type NextRequest } from "next/server";

import { getAccessToken } from "@/lib/session-store";

export const runtime = "nodejs";

const ALLOWED = new Set(["prescreen", "commit"]);

function coreBaseUrl(): string {
  return (process.env.CORE_API_URL ?? "http://localhost:8001").replace(/\/$/, "");
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ action: string }> },
): Promise<NextResponse> {
  const { action } = await context.params;
  if (!ALLOWED.has(action)) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }
  const token = await getAccessToken();
  if (!token) return NextResponse.json({ error: "unauthenticated" }, { status: 401 });

  const body = await request.text();
  let upstream: Response;
  try {
    upstream = await fetch(`${coreBaseUrl()}/api/v1/proposals/${action}`, {
      method: "POST",
      headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
      body,
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "core_api_unreachable" }, { status: 502 });
  }

  // Pass the JSON body + status through (409 block / 422 override-required carry
  // the verdict detail the UI renders).
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}
