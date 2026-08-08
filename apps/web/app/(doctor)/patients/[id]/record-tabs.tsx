"use client";
/*
 * Tabbed clinical panel (right of the copilot). A top tab bar switches between
 * Vitals (the full body map), Labs & results (graph tiles), Imaging, Medications,
 * Problems, and the encounter timeline. Vitals is the default so the body map is
 * shown fully on open. Panel content is server-rendered and passed in as props.
 */
import { useState } from "react";
import type { ReactNode } from "react";
import { Activity, Clock, FlaskConical, HeartPulse, Pill, Scan } from "lucide-react";

type Key = "vitals" | "labs" | "imaging" | "meds" | "problems" | "enc";

export function RecordTabs({
  vitals,
  labs,
  imaging,
  meds,
  problems,
  enc,
  labsCritical,
  imagingUrgent,
  medsCount,
}: {
  vitals: ReactNode;
  labs: ReactNode;
  imaging: ReactNode;
  meds: ReactNode;
  problems: ReactNode;
  enc: ReactNode;
  labsCritical?: boolean;
  imagingUrgent?: boolean;
  medsCount?: number;
}) {
  const [tab, setTab] = useState<Key>("vitals");
  const tabs: { k: Key; label: string; Icon: typeof HeartPulse; badge?: ReactNode }[] = [
    { k: "vitals", label: "Vitals", Icon: HeartPulse },
    { k: "labs", label: "Labs", Icon: FlaskConical, badge: labsCritical ? <span className="rounded-full bg-destructive-surface px-1.5 py-0.5 text-[0.5rem] font-bold uppercase text-destructive">crit</span> : undefined },
    { k: "imaging", label: "Imaging", Icon: Scan, badge: imagingUrgent ? <span className="rounded-full bg-destructive-surface px-1.5 py-0.5 text-[0.5rem] font-bold uppercase text-destructive">urgent</span> : undefined },
    { k: "meds", label: "Meds", Icon: Pill, badge: medsCount ? <span className="rounded-full bg-muted px-1.5 py-0.5 text-[0.5rem] font-bold text-muted-foreground">{medsCount}</span> : undefined },
    { k: "problems", label: "Problems", Icon: Activity },
    { k: "enc", label: "Timeline", Icon: Clock },
  ];
  const panel = { vitals, labs, imaging, meds, problems, enc }[tab];

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
      <div className="flex gap-1 overflow-x-auto border-b border-border p-1.5 scrollbar-none">
        {tabs.map(({ k, label, Icon, badge }) => {
          const on = tab === k;
          return (
            <button
              key={k}
              type="button"
              onClick={() => setTab(k)}
              aria-current={on ? "page" : undefined}
              className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-bold transition-colors ${on ? "bg-primary/12 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
              {badge}
            </button>
          );
        })}
      </div>
      <div className="p-4">{panel}</div>
    </div>
  );
}
