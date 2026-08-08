"use client";
/*
 * "Status — vitals at a glance" panel: a collapsible card that holds the body
 * map. Visible by default (status matters when opening a patient); one toggle to
 * collapse it out of the way. Content (the server-rendered BodyMap) is passed in.
 */
import { useState } from "react";
import type { ReactNode } from "react";
import { ChevronDown, HeartPulse } from "lucide-react";

export function StatusPanel({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center gap-2 px-4 py-3 text-left transition-colors hover:bg-muted">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary"><HeartPulse className="h-3.5 w-3.5" /></span>
        <b className="text-sm font-semibold">Body map</b>
        <span className="ml-auto text-xs text-muted-foreground">{open ? "hover a reading" : "collapsed"}</span>
        <ChevronDown className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open ? <div className="border-t border-border p-4">{children}</div> : null}
    </div>
  );
}
