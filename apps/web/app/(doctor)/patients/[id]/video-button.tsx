"use client";
/* Clinician entry to the telehealth room — joins the same deterministic room as
 * the patient's concierge (medagent-<phn>), so they meet live. */
import { useState } from "react";
import { Video } from "lucide-react";

import { VideoRoom } from "@/components/video-room";

export function VideoButton({ phn, displayName }: { phn: string; displayName?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-semibold hover:bg-muted"
      >
        <Video className="h-4 w-4" /> Video visit
      </button>
      {open ? <VideoRoom room={`medagent-${phn}`} displayName={displayName ?? "Clinician"} onClose={() => setOpen(false)} /> : null}
    </>
  );
}
