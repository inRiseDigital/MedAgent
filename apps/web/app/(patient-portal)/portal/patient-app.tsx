"use client";
/*
 * Patient app shell (07 §2) — a chat-first, app-like experience. Responsive:
 *   • mobile  → a phone-like single column with a sticky bottom tab bar
 *   • desktop → a left sidebar rail beside a centred content column
 * The Concierge is the default (home) tab; Summary / Record / Me are
 * server-rendered panels passed in as props (data fetched on the server, this
 * stays a thin client shell). Theme-token driven, premium `.mh` look.
 */
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Activity, FileText, MessageSquareText, User } from "lucide-react";

type TabKey = "chat" | "summary" | "record" | "me";

export function PatientApp({
  concierge,
  summary,
  record,
  me,
  rail,
}: {
  concierge: ReactNode;
  summary: ReactNode;
  record: ReactNode;
  me: ReactNode;
  rail: ReactNode;
}) {
  const [tab, setTab] = useState<TabKey>("chat");
  // A record row (server component) can ask to switch tabs via a window event.
  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (d === "chat" || d === "summary" || d === "record" || d === "me") setTab(d);
    };
    window.addEventListener("mh:tab", handler);
    return () => window.removeEventListener("mh:tab", handler);
  }, []);
  const t = useTranslations("patientNav");
  const tabs: { k: TabKey; label: string; Icon: typeof Activity }[] = [
    { k: "chat", label: t("concierge"), Icon: MessageSquareText },
    { k: "summary", label: t("summary"), Icon: Activity },
    { k: "record", label: t("record"), Icon: FileText },
    { k: "me", label: t("me"), Icon: User },
  ];

  return (
    <div className="md:flex md:gap-6 lg:gap-8">
      {/* Sidebar rail — from md up (covers unfolded foldables/tablets/desktop) */}
      <nav className="hidden md:sticky md:top-20 md:flex md:h-fit md:w-44 md:shrink-0 md:flex-col md:gap-1 lg:w-52" aria-label="Patient app">
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

      {/* Content column. Chat fills the width; reading-oriented tabs stay at a
          comfortable measure. Non-chat tabs get bottom padding to clear the
          fixed mobile bar; the chat manages its own height. */}
      <div className="min-w-0 flex-1">
        {/* Chat spans the column so it uses the desktop space; bubbles are capped
            for readability in CSS. Other tabs stay centred at reading width. */}
        <div className={tab === "chat" ? "block" : "hidden"}>{concierge}</div>
        <div className="mx-auto w-full max-w-2xl md:mx-0">
          <div className={tab === "summary" ? "block pb-28 md:pb-2" : "hidden"}>{summary}</div>
          <div className={tab === "record" ? "block pb-28 md:pb-2" : "hidden"}>{record}</div>
          <div className={tab === "me" ? "block pb-28 md:pb-2" : "hidden"}>{me}</div>
        </div>
      </div>

      {/* Desktop right rail — at-a-glance context beside the chat (chat tab only) */}
      {tab === "chat" ? (
        <aside className="hidden xl:block xl:w-80 xl:shrink-0 2xl:w-96">{rail}</aside>
      ) : null}

      {/* Mobile bottom tab bar — FIXED to the viewport so it never scrolls away.
          A short gradient masks content passing behind the floating pill. */}
      <nav
        className="fixed inset-x-0 bottom-0 z-30 bg-gradient-to-t from-[color:var(--mh-bg)] via-[color:var(--mh-bg)]/85 to-transparent pt-4 md:hidden"
        aria-label="Patient app"
      >
        <div className="mx-auto max-w-lg px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <div className="flex gap-1 rounded-2xl border border-border bg-card/90 p-1.5 shadow-lg backdrop-blur">
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
          </div>
        </div>
      </nav>
    </div>
  );
}
