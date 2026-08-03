/*
 * BFF refill endpoint (FR-5). Requests a medication refill for the SIGNED-IN
 * patient — PHN from the session, never the client. Forwards to core-api, which
 * creates a FHIR Task into the prescriber/pharmacy inbox (does not dispense).
 */
import { NextResponse } from "next/server";

import { getAccessToken, getSession } from "@/lib/session-store";

export const runtime = "nodejs";

function coreBase(): string {
  return (process.env.CORE_API_URL ?? "http://localhost:8001").replace(/\/$/, "");
}

export async function POST(request: Request): Promise<NextResponse> {
  const session = await getSession();
  const token = await getAccessToken();
  if (!session?.patientPhn || !token) return NextResponse.json({ error: "no_patient" }, { status: 401 });
  const body = (await request.json().catch(() => ({}))) as { medication?: string; note?: string };
  if (!body.medication) return NextResponse.json({ error: "medication_required" }, { status: 422 });
  const res = await fetch(`${coreBase()}/api/v1/patients/${encodeURIComponent(session.patientPhn)}/refill`, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify({ medication: body.medication, note: body.note }),
    cache: "no-store",
  });
  return new NextResponse(await res.text(), { status: res.status, headers: { "content-type": "application/json" } });
}
