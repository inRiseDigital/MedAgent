/*
 * BFF booking endpoint (FR-9.5, patient self-service). GET lists free slots;
 * POST books a specific slot for the SIGNED-IN patient — the PHN comes from the
 * session, never the client, so a patient can only book as themselves. Forwards
 * to core-api with the session token.
 */
import { NextResponse } from "next/server";

import { getAccessToken, getSession } from "@/lib/session-store";

export const runtime = "nodejs";

function coreBase(): string {
  return (process.env.CORE_API_URL ?? "http://localhost:8001").replace(/\/$/, "");
}

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
  const res = await fetch(`${coreBase()}/api/v1/schedule/slots?${params.toString()}`, {
    headers: { authorization: `Bearer ${a.token}` },
    cache: "no-store",
  });
  return new NextResponse(await res.text(), { status: res.status, headers: { "content-type": "application/json" } });
}

export async function POST(request: Request): Promise<NextResponse> {
  const a = await auth();
  if (!a) return NextResponse.json({ error: "no_patient" }, { status: 401 });
  const body = (await request.json().catch(() => ({}))) as { slot?: string; reason?: string };
  if (!body.slot) return NextResponse.json({ error: "slot_required" }, { status: 422 });
  const res = await fetch(`${coreBase()}/api/v1/schedule/book`, {
    method: "POST",
    headers: { authorization: `Bearer ${a.token}`, "content-type": "application/json" },
    body: JSON.stringify({ slot: body.slot, patient: a.phn, reason: body.reason }),
    cache: "no-store",
  });
  return new NextResponse(await res.text(), { status: res.status, headers: { "content-type": "application/json" } });
}
