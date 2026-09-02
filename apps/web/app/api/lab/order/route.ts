/*
 * BFF lab-order proxy (agent-driven ordering). Files a lab order the doctor
 * confirmed in the copilot as a FHIR ServiceRequest via the gated core-api route,
 * attaching the session's access token server-side. The model proposed; the
 * doctor's tap commits.
 */
import { NextResponse } from "next/server";

import { proxyToCore } from "@/lib/bff";
import { getAccessToken } from "@/lib/session-store";

export const runtime = "nodejs";

export async function POST(request: Request): Promise<NextResponse> {
  const token = await getAccessToken();
  if (!token) return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  const body = (await request.json().catch(() => ({}))) as {
    patient_id?: string; test?: string; priority?: string;
  };
  if (!body.patient_id || !body.test) return NextResponse.json({ error: "patient_and_test_required" }, { status: 422 });

  return proxyToCore("/api/v1/lab/order", {
    method: "POST",
    token,
    body: JSON.stringify({ patient: body.patient_id, test: body.test, priority: body.priority }),
  });
}
