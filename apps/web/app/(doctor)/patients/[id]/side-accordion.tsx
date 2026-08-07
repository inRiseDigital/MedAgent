"use client";
/*
 * Collapsible side rail for the clinician session: safety flags, record detail,
 * and the write tools (clinical entry, prescription). Accordion behaviour — opening
 * one section auto-collapses the others — so the long list of panels stays compact
 * beside the central chat. Server-rendered content is passed in as `content`.
 */
import { useState } from "react";
import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";

export type AccordionItem = {
  id: string;
  title: string;
  icon?: ReactNode;
  badge?: { text: string; tone: "destructive" | "warning" | "muted" };
  content: ReactNode;
};

const BADGE: Record<string, string> = {
  destructive: "bg-destructive-surface text-destructive",
  warning: "bg-warning-surface text-warning",
  muted: "bg-muted text-muted-foreground",
};

export function SideAccordion({ items, defaultOpenId }: { items: AccordionItem[]; defaultOpenId?: string }) {
  const [open, setOpen] = useState<string | null>(defaultOpenId ?? items[0]?.id ?? null);
  return (
    <div className="space-y-2">
      {items.map((it) => {
        const isOpen = open === it.id;
        return (
          <div key={it.id} className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
            <button
              type="button"
              onClick={() => setOpen(isOpen ? null : it.id)}
              aria-expanded={isOpen}
              className="flex w-full items-center gap-2 px-4 py-3 text-left transition-colors hover:bg-muted"
            >
              {it.icon ? <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">{it.icon}</span> : null}
              <span className="text-sm font-semibold">{it.title}</span>
              {it.badge ? (
                <span className={`ml-1 rounded-full px-2 py-0.5 text-[0.6rem] font-bold uppercase ${BADGE[it.badge.tone]}`}>{it.badge.text}</span>
              ) : null}
              <ChevronDown className={`ml-auto h-4 w-4 shrink-0 text-muted-foreground transition-transform ${isOpen ? "rotate-180" : ""}`} />
            </button>
            {isOpen ? <div className="border-t border-border p-4">{it.content}</div> : null}
          </div>
        );
      })}
    </div>
  );
}
