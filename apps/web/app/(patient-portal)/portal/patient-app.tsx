"use client";
/*
 * Patient app shell (07 §2) — a chat-first, app-like experience with a bottom
 * tab bar. The Concierge is the default (home) tab; Health / Record / Me are
 * server-rendered panels passed in as props (so their data is fetched on the
 * server and this stays a thin client shell). Theme-aware, mobile-first.
 */
import { useState } from "react";
import type { ReactNode } from "react";
import { Activity, FileText, MessageSquareText, User } from "lucide-react";

type TabKey = "chat" | "health" | "record" | "me";

export function PatientApp({
  concierge,
  health,
  record,
  me,
}: {
  concierge: ReactNode;
  health: ReactNode;
  record: ReactNode;
  me: ReactNode;
}) {
  const [tab, setTab] = useState<TabKey>("chat");
  const tabs: { k: TabKey; label: string; Icon: typeof Activity }[] = [
    { k: "chat", label: "Concierge", Icon: MessageSquareText },
    { k: "health", label: "Health", Icon: Activity },
    { k: "record", label: "Record", Icon: FileText },
    { k: "me", label: "Me", Icon: User },
  ];
  return (
    <div className="flex min-h-[calc(100dvh-8.5rem)] flex-col">
      <div className="flex-1">
        <div className={tab === "chat" ? "block" : "hidden"}>{concierge}</div>
        <div className={tab === "health" ? "block" : "hidden"}>{health}</div>
        <div className={tab === "record" ? "block" : "hidden"}>{record}</div>
        <div className={tab === "me" ? "block" : "hidden"}>{me}</div>
      </div>
      <nav
        className="sticky bottom-0 z-10 mt-4 flex gap-1 rounded-2xl border border-border bg-card/85 p-1.5 shadow-lg backdrop-blur"
        aria-label="Patient app"
      >
        {tabs.map(({ k, label, Icon }) => {
          const on = tab === k;
          return (
            <button
              key={k}
              type="button"
              onClick={() => setTab(k)}
              aria-current={on ? "page" : undefined}
              className={`flex flex-1 flex-col items-center gap-1 rounded-xl px-2 py-2 text-[0.68rem] font-semibold transition-colors ${
                on ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon className="h-5 w-5" />
              {label}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
