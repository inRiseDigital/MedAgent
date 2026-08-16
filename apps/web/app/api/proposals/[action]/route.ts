/*
 * BFF proposals proxy (06 §7). The workspace posts a proposal here
 * (cookie-authenticated); this attaches the session access token server-side and
 * forwards to core-api's write-back endpoints. `action` is `prescreen` (verdict
 * preview) or `commit` (safety-gated write + audit). core-api re-screens
 * prescriptions itself — this is a transport, not the safety boundary.
 */
import { NextResponse, type NextRequest } from "next/server";

import { proxyToCore } from "@/lib/bff";
import { getAccessToken } from "@/lib/session-store";

export const runtime = "nodejs";

const ALLOWED = new Set(["prescreen", "commit"]);

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

  return proxyToCore(`/api/v1/proposals/${action}`, { method: "POST", token, body: await request.text() });
}
