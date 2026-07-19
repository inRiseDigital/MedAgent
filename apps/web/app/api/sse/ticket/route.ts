/*
 * BFF SSE-ticket endpoint (docs/solution/02 §11). The browser's EventSource
 * cannot set an Authorization header, so the flow is:
 *
 *   1. lib/sse.ts POSTs here (cookie-authenticated, same-origin).
 *   2. This handler pulls the session's access token server-side and exchanges
 *      it at notify-service `POST /notify/ticket` for a single-use, 30 s,
 *      opaque ticket.
 *   3. The browser opens `${NEXT_PUBLIC_NOTIFY_STREAM_URL}?ticket=...`.
 *
 * The bearer token never leaves the server; only the single-use opaque ticket
 * reaches the browser (dead after first redemption, log-scrubbed at the
 * gateway — 02 ADR I-10).
 */
import { NextResponse, type NextRequest } from "next/server";

import { getAccessToken } from "@/lib/session-store";

export const runtime = "nodejs";

interface TicketBody {
  /** Staff callers may request a facility check-in channel (notify-service
   *  authorises it against the caller's role). */
  facilityId?: string;
}

function notifyBaseUrl(): string {
  return (process.env.NOTIFY_SERVICE_URL ?? "http://localhost:8003").replace(/\/$/, "");
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const accessToken = await getAccessToken();
  if (!accessToken) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }

  let body: TicketBody = {};
  try {
    // Body is optional; a malformed/empty body just means "personal channel".
    const text = await request.text();
    if (text) body = JSON.parse(text) as TicketBody;
  } catch {
    body = {};
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${notifyBaseUrl()}/notify/ticket`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${accessToken}`,
        "content-type": "application/json",
      },
      cache: "no-store",
      body: JSON.stringify({ facility_id: body.facilityId ?? null }),
    });
  } catch {
    return NextResponse.json({ error: "notify_unreachable" }, { status: 502 });
  }

  if (!upstream.ok) {
    return NextResponse.json({ error: "ticket_denied" }, { status: upstream.status });
  }

  const { ticket, expires_in } = (await upstream.json()) as {
    ticket: string;
    expires_in: number;
  };
  return NextResponse.json({ ticket, expiresIn: expires_in });
}
