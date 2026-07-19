/*
 * Live queue (FR-2.1, 06 §3). Server component: fetches the initial queue
 * through the BFF (session token attached server-side) and hands it to the
 * client QueueList, which keeps it live over SSE. Arrival order is always
 * server-assigned — never client-sorted.
 */
import { currentFacilityId, fetchQueue, type QueueRow } from "@/lib/api";
import { QueueList } from "./queue-list";

// Always render fresh — the queue is real-time operational state.
export const dynamic = "force-dynamic";

export default async function QueuePage() {
  const facilityId = currentFacilityId();

  let initialRows: QueueRow[] = [];
  let initialError = false;
  try {
    initialRows = await fetchQueue(facilityId);
  } catch {
    // The client will retry via the BFF poll; render the shell with a banner
    // rather than failing the page (care is never blocked, 06 §10).
    initialError = true;
  }

  return (
    <QueueList facilityId={facilityId} initialRows={initialRows} initialError={initialError} />
  );
}
