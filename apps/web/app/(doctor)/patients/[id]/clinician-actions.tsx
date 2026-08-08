"use client";
/*
 * Quick-action bar in the patient header (matches the cockpit prototype):
 * Prescribe → the real Rx sign-off panel; Order / Note → the real clinical-entry
 * form; Video → the real telehealth start. Prescribe/Order/Note open in a modal
 * so they're one tap from anywhere without cluttering the layout.
 */
import { useState } from "react";
import { ClipboardList, FileText, Pill, X } from "lucide-react";

import { ClinicalEntry } from "./clinical-entry";
import { ProposalPanel } from "./proposal-panel";
import { VideoButton } from "./video-button";

type Modal = null | "rx" | "entry";

export function ClinicianActions({ patientId, videoPhn }: { patientId: string; videoPhn?: string }) {
  const [modal, setModal] = useState<Modal>(null);
  const btn = "inline-flex items-center gap-2 rounded-xl border border-border bg-muted px-3.5 py-2 text-xs font-bold text-foreground transition-colors hover:bg-border/60";
  return (
    <>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => setModal("rx")} className="inline-flex items-center gap-2 rounded-xl bg-primary px-3.5 py-2 text-xs font-bold text-primary-foreground hover:brightness-110">
          <Pill className="h-4 w-4" /> Prescribe
        </button>
        <button type="button" onClick={() => setModal("entry")} className={btn}><ClipboardList className="h-4 w-4" /> Order</button>
        <button type="button" onClick={() => setModal("entry")} className={btn}><FileText className="h-4 w-4" /> Note</button>
        {videoPhn ? <VideoButton phn={videoPhn} /> : null}
      </div>

      {modal ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm" onClick={(e) => { if (e.target === e.currentTarget) setModal(null); }}>
          <div className="w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-card shadow-2xl">
            <div className="flex items-center gap-2 border-b border-border px-4 py-3">
              <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary">
                {modal === "rx" ? <Pill className="h-3.5 w-3.5" /> : <ClipboardList className="h-3.5 w-3.5" />}
              </span>
              <h3 className="text-sm font-semibold">{modal === "rx" ? "New prescription · sign-off" : "Clinical entry"}</h3>
              <button type="button" onClick={() => setModal(null)} aria-label="Close" className="ml-auto flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-[75vh] overflow-y-auto p-4">
              {modal === "rx" ? <ProposalPanel patientId={patientId} /> : <ClinicalEntry patientId={patientId} />}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
