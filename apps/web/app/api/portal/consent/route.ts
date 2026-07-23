/*
 * BFF consent endpoint (FR-5.2). Reads/writes the signed-in patient's OWN
 * consent — the PHN comes from the session, never the client, so a patient can
 * only ever change their own. Forwards to core-api with the session token.
 */
import { NextResponse } from "next/server";

import { getAccessToken, getSession } from "@/lib/session-store";

export const runtime = "nodejs";

function coreBase(): string {
  return (process.env.CORE_API_URL ?? "http://localhost:8001").replace(/\/$/, "");
}

async function target(): Promise<{ url: string; token: string } | null> {
  const session = await getSession();
  const token = await getAccessToken();
  if (!session?.patientPhn || !token) return null;
  return { url: `${coreBase()}/api/v1/patients/${encodeURIComponent(session.patientPhn)}/consent`, token };
}

export async function GET(): Promise<NextResponse> {
  const t = await target();
  if (!t) return NextResponse.json({ error: "no_patient" }, { status: 401 });
  const res = await fetch(t.url, { headers: { authorization: `Bearer ${t.token}` }, cache: "no-store" });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}

export async function PUT(request: Request): Promise<NextResponse> {
  const t = await target();
  if (!t) return NextResponse.json({ error: "no_patient" }, { status: 401 });
  const res = await fetch(t.url, {
    method: "PUT",
    headers: { authorization: `Bearer ${t.token}`, "content-type": "application/json" },
    body: await request.text(),
    cache: "no-store",
  });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}
