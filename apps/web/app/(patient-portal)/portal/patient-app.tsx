"use client";
/*
 * Patient app shell (07 §2) — a chat-first, app-like experience. Responsive:
 *   • mobile  → a phone-like single column with a sticky bottom tab bar
 *   • desktop → a left sidebar rail beside a centred content column
 * The Concierge is the default (home) tab; Summary / Record / Me are
 * server-rendered panels passed in as props (data fetched on the server, this
 * stays a thin client shell). Theme-token driven, premium `.mh` look.
 */
import { useState } from "react";
import type { ReactNode } from "react";
import { Activity, FileText, MessageSquareText, User } from "lucide-react";

type TabKey = "chat" | "summary" | "record" | "me";

export function PatientApp({
  concierge,
  summary,
  record,
  me,
}: {
  concierge: ReactNode;
  summary: ReactNode;
  record: ReactNode;
  me: ReactNode;
}) {
  const [tab, setTab] = useState<TabKey>("chat");
  const tabs: { k: TabKey; label: string; Icon: typeof Activity }[] = [
    { k: "chat", label: "Concierge", Icon: MessageSquareText },
    { k: "summary", label: "Summary", Icon: Activity },
    { k: "record", label: "Record", Icon: FileText },
    { k: "me", label: "Me", Icon: User },
  ];

  return (
    <div className="lg:flex lg:gap-8">
      {/* Desktop sidebar rail */}
      <nav className="hidden lg:sticky lg:top-20 lg:flex lg:h-fit lg:w-52 lg:shrink-0 lg:flex-col lg:gap-1" aria-label="Patient app">
        {tabs.map(({ k, label, Icon }) => {
          const on = tab === k;
          return (
            <button
              key={k}
              type="button"
              onClick={() => setTab(k)}
              aria-current={on ? "page" : undefined}
              className={`flex items-center gap-3 rounded-xl px-3.5 py-3 text-sm font-semibold transition-colors ${
                on ? "bg-primary/12 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              <Icon className="h-5 w-5 shrink-0" />
              {label}
            </button>
          );
        })}
      </nav>

      {/* Content column */}
      <div className="flex min-h-[calc(100dvh-8.5rem)] min-w-0 flex-1 flex-col">
        <div className="mx-auto w-full max-w-2xl flex-1 lg:mx-0">
          <div className={tab === "chat" ? "block" : "hidden"}>{concierge}</div>
          <div className={tab === "summary" ? "block" : "hidden"}>{summary}</div>
          <div className={tab === "record" ? "block" : "hidden"}>{record}</div>
          <div className={tab === "me" ? "block" : "hidden"}>{me}</div>
        </div>

        {/* Mobile bottom tab bar */}
        <nav
          className="sticky bottom-0 z-10 mt-4 flex gap-1 rounded-2xl border border-border bg-card/85 p-1.5 shadow-lg backdrop-blur lg:hidden"
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
    </div>
  );
}
