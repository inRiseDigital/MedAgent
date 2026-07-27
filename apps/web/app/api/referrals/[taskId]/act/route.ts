/*
 * BFF referral-action proxy (FR-9.3). The receiving-facility worklist posts an
 * accept/reject/start/complete here (cookie-authenticated); this attaches the
 * session access token server-side and forwards to core-api, which enforces the
 * transition matrix. Transport only — the state machine lives in core-api.
 */
import { NextResponse, type NextRequest } from "next/server";

import { getAccessToken } from "@/lib/session-store";

export const runtime = "nodejs";

function coreBaseUrl(): string {
  return (process.env.CORE_API_URL ?? "http://localhost:8001").replace(/\/$/, "");
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ taskId: string }> },
): Promise<NextResponse> {
  const { taskId } = await context.params;
  if (!/^[A-Za-z0-9-]{1,64}$/.test(taskId)) {
    return NextResponse.json({ error: "bad_task_id" }, { status: 400 });
  }
  const token = await getAccessToken();
  if (!token) return NextResponse.json({ error: "unauthenticated" }, { status: 401 });

  const body = await request.text();
  let upstream: Response;
  try {
    upstream = await fetch(`${coreBaseUrl()}/api/v1/referrals/${encodeURIComponent(taskId)}/act`, {
      method: "POST",
      headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
      body,
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "core_api_unreachable" }, { status: 502 });
  }
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}
