"use client";
/*
 * Patient app shell (07 §2) — a borderless, conversation-first canvas. The chat
 * IS the app: it fills the surface. Summary / Record / Me are no longer word-tabs
 * stealing layout — they "bloom" over the canvas as a right slide-over sheet,
 * summoned from a quiet icon rail (or by the record's `mh:tab` deep-link bus). A
 * body-data dock rides alongside on wide screens. Mobile-first: the same structure
 * is what the future mobile app renders. Theme-token driven, premium `.mh` look.
 */
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Activity, FileText, User, X } from "lucide-react";

type PanelKey = "summary" | "record" | "me";

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
  // null = the pure chat canvas; a key = that panel is bloomed over the canvas.
  const [panel, setPanel] = useState<PanelKey | null>(null);

  // The record/summary (server components) ask to open a panel via a window event.
  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (d === "summary" || d === "record" || d === "me") setPanel(d);
      else if (d === "chat") setPanel(null);
    };
    window.addEventListener("mh:tab", handler);
    return () => window.removeEventListener("mh:tab", handler);
  }, []);

  // Esc closes the sheet; lock body scroll while it's open.
  useEffect(() => {
    if (!panel) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setPanel(null); };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [panel]);

  const t = useTranslations("patientNav");
  const items: { k: PanelKey; label: string; Icon: typeof Activity }[] = [
    { k: "summary", label: t("summary"), Icon: Activity },
    { k: "record", label: t("record"), Icon: FileText },
    { k: "me", label: t("me"), Icon: User },
  ];
  const panelContent = panel === "summary" ? summary : panel === "record" ? record : panel === "me" ? me : null;
  const panelLabel = items.find((i) => i.k === panel)?.label ?? "";

  return (
    <div className="md:flex md:gap-4 lg:gap-6">
      {/* Summon rail — a quiet icon strip (horizontal on mobile, a slim vertical
          rail on desktop) that blooms a panel. Replaces the old word-tab sidebar. */}
      <nav className="mh-summon md:sticky md:top-20 md:self-start md:shrink-0" aria-label={t("summary") + " / " + t("record") + " / " + t("me")}>
        {items.map(({ k, label, Icon }) => (
          <button
            key={k}
            type="button"
            onClick={() => setPanel((p) => (p === k ? null : k))}
            aria-pressed={panel === k}
            className={`mh-summon-btn ${panel === k ? "on" : ""}`}
          >
            <Icon className="h-5 w-5" />
            <span>{label}</span>
          </button>
        ))}
      </nav>

      {/* The chat canvas — the app. Fills the column. */}
      <div className="min-w-0 flex-1">{concierge}</div>

      {/* Body-data dock (xl+) — ambient context beside the canvas. */}
      <aside className="hidden xl:block xl:w-80 xl:shrink-0 2xl:w-96">{rail}</aside>

      {/* Right slide-over: the summoned panel blooms over the canvas. */}
      {panel ? (
        <>
          <div className="mh-sheet-scrim" onClick={() => setPanel(null)} aria-hidden />
          <aside className="mh-sheet" role="dialog" aria-modal="true" aria-label={panelLabel}>
            <div className="mh-sheet-head">
              <span>{panelLabel}</span>
              <button type="button" onClick={() => setPanel(null)} aria-label="Close" className="mh-sheet-x">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="mh-sheet-body">{panelContent}</div>
          </aside>
        </>
      ) : null}
    </div>
  );
}
