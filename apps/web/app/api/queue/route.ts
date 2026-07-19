/*
 * BFF queue endpoint. The client QueueList refetches through here on each SSE
 * check-in event (and on the degraded-mode poll) so the browser never holds a
 * bearer token and the server-assigned arrival order is always authoritative
 * (docs/solution/06 §3).
 */
import { NextResponse } from "next/server";

import { ApiError, currentFacilityId, fetchQueue } from "@/lib/api";

export const runtime = "nodejs";

export async function GET(): Promise<NextResponse> {
  try {
    const rows = await fetchQueue(currentFacilityId());
    return NextResponse.json({ facilityId: currentFacilityId(), rows });
  } catch (err) {
    if (err instanceof ApiError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    return NextResponse.json({ error: "core_api_unreachable" }, { status: 502 });
  }
}
