/*
 * BFF refill endpoint (FR-5). Requests a medication refill for the SIGNED-IN
 * patient — PHN from the session, never the client. Forwards to core-api, which
 * creates a FHIR Task into the prescriber/pharmacy inbox (does not dispense).
 */
import { NextResponse } from "next/server";

import { proxyToCore } from "@/lib/bff";
import { getAccessToken, getSession } from "@/lib/session-store";

export const runtime = "nodejs";

export async function POST(request: Request): Promise<NextResponse> {
  const session = await getSession();
  const token = await getAccessToken();
  if (!session?.patientPhn || !token) return NextResponse.json({ error: "no_patient" }, { status: 401 });
  const body = (await request.json().catch(() => ({}))) as { medication?: string; note?: string };
  if (!body.medication) return NextResponse.json({ error: "medication_required" }, { status: 422 });
  return proxyToCore(`/api/v1/patients/${encodeURIComponent(session.patientPhn)}/refill`, {
    method: "POST",
    token,
    body: JSON.stringify({ medication: body.medication, note: body.note }),
  });
}
