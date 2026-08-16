/*
 * BFF booking endpoint (FR-9.5, patient self-service). GET lists free slots;
 * POST books a specific slot for the SIGNED-IN patient — the PHN comes from the
 * session, never the client, so a patient can only book as themselves. Forwards
 * to core-api with the session token.
 */
import { NextResponse } from "next/server";

import { proxyToCore } from "@/lib/bff";
import { getAccessToken, getSession } from "@/lib/session-store";

export const runtime = "nodejs";

async function auth(): Promise<{ token: string; phn: string } | null> {
  const session = await getSession();
  const token = await getAccessToken();
  if (!session?.patientPhn || !token) return null;
  return { token, phn: session.patientPhn };
}

export async function GET(request: Request): Promise<NextResponse> {
  const a = await auth();
  if (!a) return NextResponse.json({ error: "no_patient" }, { status: 401 });
  const qs = new URL(request.url).searchParams;
  const params = new URLSearchParams();
  const specialty = qs.get("specialty");
  const facility = qs.get("facility");
  if (specialty) params.set("specialty", specialty);
  if (facility) params.set("facility", facility);
  return proxyToCore(`/api/v1/schedule/slots?${params.toString()}`, { token: a.token });
}

export async function POST(request: Request): Promise<NextResponse> {
  const a = await auth();
  if (!a) return NextResponse.json({ error: "no_patient" }, { status: 401 });
  const body = (await request.json().catch(() => ({}))) as { slot?: string; reason?: string };
  if (!body.slot) return NextResponse.json({ error: "slot_required" }, { status: 422 });
  return proxyToCore(`/api/v1/schedule/book`, {
    method: "POST",
    token: a.token,
    body: JSON.stringify({ slot: body.slot, patient: a.phn, reason: body.reason }),
  });
}
