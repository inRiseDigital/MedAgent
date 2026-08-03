"use client";
/* Live patient notifications — subscribes to the personal SSE channel and shows
 * a toast when the record changes (booking confirmed, refill received, …).
 * Reuses the ticket-based SSE client. */
import { useEffect, useState } from "react";
import { Bell } from "lucide-react";

import { createEventStream } from "@/lib/sse";

type Toast = { id: number; title: string; body?: string };

export function Notifications() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  useEffect(() => {
    let counter = 0;
    const handle = createEventStream({
      onEvent: (e) => {
        try {
          const d = JSON.parse(e.data) as { title?: string; body?: string };
          const title = d.title;
          if (!title) return;
          const body = d.body;
          const id = ++counter;
          setToasts((t) => [...t, { id, title, body }]);
          window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
        } catch {
          /* heartbeat / non-JSON — ignore */
        }
      },
    });
    return () => handle.close();
  }, []);

  if (!toasts.length) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 top-3 z-50 flex flex-col items-center gap-2 px-4">
      {toasts.map((t) => (
        <div key={t.id} className="pointer-events-auto w-full max-w-sm rounded-2xl border border-border bg-card p-3.5 shadow-lg" style={{ animation: "mh-rise .3s ease both" }}>
          <div className="flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Bell className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-semibold">{t.title}</p>
              {t.body ? <p className="text-xs text-muted-foreground">{t.body}</p> : null}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
