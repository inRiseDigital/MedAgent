/*
 * BFF consult-agenda proxy (Horizon-1, the doctor consult session). The copilot
 * posts a patient id; this attaches the session's access token server-side and
 * asks the agent-service for a grounded, cited consultation agenda. Clinical
 * surface — the caller is an authenticated clinician (session token).
 */
import { NextResponse } from "next/server";

import { getAccessToken } from "@/lib/session-store";

export const runtime = "nodejs";

function agentBaseUrl(): string {
  return (process.env.AGENT_SERVICE_URL ?? "http://localhost:8002").replace(/\/$/, "");
}

export async function POST(request: Request): Promise<NextResponse> {
  const token = await getAccessToken();
  if (!token) return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  const body = (await request.json().catch(() => ({}))) as { patient_id?: string };
  if (!body.patient_id) return NextResponse.json({ error: "patient_required" }, { status: 422 });

  try {
    const res = await fetch(`${agentBaseUrl()}/api/v1/consult/agenda`, {
      method: "POST",
      headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
      body: JSON.stringify({ patient_id: body.patient_id, audience: "clinician" }),
      cache: "no-store",
    });
    return new NextResponse(await res.text(), {
      status: res.status,
      headers: { "content-type": "application/json" },
    });
  } catch {
    return NextResponse.json({ error: "agent_unreachable" }, { status: 502 });
  }
}
