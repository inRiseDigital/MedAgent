"use client";

/*
 * Live queue (FR-2.1) — S1 scaffold, implemented in S2/S3 per
 * docs/solution/11. Target design (06 §3):
 * - SSE-driven from notify-service (check-in events), arrival order
 *   preserved via server-assigned sequence — never client sort.
 * - Rows: name, PHN fragment, arrival time, wait duration, check-in
 *   method badge (face/manual), manual-verification flag (05 §3 step 6).
 * - REAL connection-state indicator from EventSource health — not the
 *   prototype's decorative pulse.
 * - Degraded mode: poll GET /queue every 15 s while SSE is down, with a
 *   banner (06 §10) — care is never blocked.
 */
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Badge, Card, CardContent, CardHeader, CardTitle, type BadgeProps } from "@medagent/ui";
import type { ConnectionState } from "@/lib/sse";

interface QueueEntry {
  sequence: number;
  displayName: string;
  phnFragment: string;
  arrivedAt: string;
  method: "face" | "manual";
  needsManualVerification: boolean;
}

/**
 * SSE hook stub — S2 wires createEventStream from @/lib/sse:
 *
 *   const stream = createEventStream({
 *     eventTypes: ["checkin", "queue-update"],
 *     onEvent: (ev) => patchQueryCache(JSON.parse(ev.data)),  // 06 §5
 *     onStateChange: setConnectionState,
 *   });
 *   return () => stream.close();
 *
 * plus the 15 s polling fallback while the stream is down. Until
 * notify-service exists there is nothing to connect to, so the stub
 * reports an honest "closed" state instead of pretending to listen.
 */
function useQueueStream(): { connectionState: ConnectionState; entries: QueueEntry[] } {
  const [connectionState] = useState<ConnectionState>("closed");
  const [entries] = useState<QueueEntry[]>([]);
  const started = useRef(false);
  useEffect(() => {
    started.current = true; // S2: open the stream here (see docstring).
  }, []);
  return { connectionState, entries };
}

const CONNECTION_BADGE: Record<ConnectionState, BadgeProps["variant"]> = {
  connecting: "neutral",
  open: "pass",
  reconnecting: "warn",
  closed: "block",
};

export default function QueuePage() {
  const t = useTranslations("queue");
  const { connectionState, entries } = useQueueStream();

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{t("title")}</h1>
          <p className="text-muted-foreground">{t("description")}</p>
        </div>
        <Badge variant={CONNECTION_BADGE[connectionState]}>
          {t(`connection.${connectionState}`)}
        </Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
        </CardHeader>
        <CardContent>
          {/* aria-live region for queue updates (06 §4.5). */}
          <ul aria-live="polite" className="divide-y divide-border">
            {entries.length === 0 ? (
              <li className="py-8 text-center text-muted-foreground">{t("empty")}</li>
            ) : (
              entries.map((entry) => (
                <li key={entry.sequence} className="flex h-11 items-center gap-3">
                  <span className="tabular-nums text-muted-foreground">{entry.sequence}</span>
                  <span className="font-medium">{entry.displayName}</span>
                  <span className="text-muted-foreground">{entry.phnFragment}</span>
                </li>
              ))
            )}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
