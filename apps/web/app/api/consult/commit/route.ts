/*
 * BFF consult-commit proxy (Horizon-1 / S7 write-back). Files a completed consult
 * as a FHIR Encounter + note via the gated core-api route, attaching the session's
 * access token server-side. The clinician has confirmed each agenda item; this is
 * the sign-and-file step.
 */
import { NextResponse } from "next/server";

import { proxyToCore } from "@/lib/bff";
import { getAccessToken } from "@/lib/session-store";

export const runtime = "nodejs";

export async function POST(request: Request): Promise<NextResponse> {
  const token = await getAccessToken();
  if (!token) return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  const body = (await request.json().catch(() => ({}))) as {
    patient_id?: string; items?: string[]; note?: string; reason?: string;
  };
  if (!body.patient_id) return NextResponse.json({ error: "patient_required" }, { status: 422 });

  return proxyToCore("/api/v1/consult/encounter", {
    method: "POST",
    token,
    body: JSON.stringify({
      patient: body.patient_id,
      items: body.items ?? [],
      note: body.note,
      reason: body.reason,
    }),
  });
}
