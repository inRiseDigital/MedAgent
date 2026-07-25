"use client";

/*
 * Live queue list (06 §3). Holds the server-fetched rows and keeps them live:
 * - subscribes to notify-service SSE via createEventStream (single-use ticket
 *   handoff, 02 §11); on each check-in / queue event it refetches the BFF
 *   /api/queue so the server-assigned arrival order stays authoritative;
 * - shows a REAL connection-state badge from EventSource health, not a
 *   decorative pulse (the prototype's flaw, 06 §3);
 * - degraded mode: while the stream is down it polls /api/queue every 15 s and
 *   shows a banner — care is never blocked (06 §10).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Badge, Card, CardContent, CardHeader, CardTitle, type BadgeProps } from "@medagent/ui";
import type { QueueRow } from "@/lib/api";
import { createEventStream, type ConnectionState } from "@/lib/sse";

const CONNECTION_BADGE: Record<ConnectionState, BadgeProps["variant"]> = {
  connecting: "neutral",
  open: "pass",
  reconnecting: "warn",
  closed: "block",
  unauthorized: "block",
};

const POLL_INTERVAL_MS = 15_000;

interface QueueListProps {
  facilityId: string;
  initialRows: QueueRow[];
  initialError: boolean;
}

export function QueueList({ facilityId, initialRows, initialError }: QueueListProps) {
  const t = useTranslations("queue");
  const [rows, setRows] = useState<QueueRow[]>(initialRows);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [stale, setStale] = useState(initialError);

  const refetch = useCallback(async () => {
    try {
      const res = await fetch("/api/queue", { cache: "no-store" });
      if (!res.ok) {
        setStale(true);
        return;
      }
      const data = (await res.json()) as { rows: QueueRow[] };
      setRows(data.rows);
      setStale(false);
    } catch {
      setStale(true);
    }
  }, []);

  // Live updates over SSE; refetch on any event so ordering stays server-authoritative.
  useEffect(() => {
    const stream = createEventStream({
      eventTypes: ["message", "checkin", "queue-update"],
      onEvent: () => void refetch(),
      onStateChange: setConnectionState,
    });
    return () => stream.close();
  }, [refetch]);

  // Degraded-mode poll: only while the stream is not open.
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    // No point polling once the session is gone — the poll would 401 too.
    if (connectionState === "open" || connectionState === "unauthorized") {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
      return;
    }
    pollRef.current = setInterval(() => void refetch(), POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [connectionState, refetch]);

  const sessionExpired = connectionState === "unauthorized";

  // A dead SSE session means the login is gone — tell the app-wide SessionGuard
  // to show its blocking re-login dialog immediately (not just this banner).
  useEffect(() => {
    if (sessionExpired) window.dispatchEvent(new Event("medagent:session-expired"));
  }, [sessionExpired]);
  const showDegraded =
    !sessionExpired && (stale || (connectionState !== "open" && connectionState !== "connecting"));

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

      {sessionExpired ? (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-destructive/40 bg-destructive-surface px-3 py-2 text-sm text-destructive"
        >
          <span>{t("sessionExpired")}</span>
          <a
            href="/api/auth/login"
            className="rounded-md bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t("signIn")}
          </a>
        </div>
      ) : showDegraded ? (
        <p role="status" className="rounded-md border border-warning bg-warning-surface px-3 py-2 text-sm text-warning">
          {t("degradedBanner")}
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
        </CardHeader>
        <CardContent>
          {/* aria-live region for queue updates (06 §4.5). */}
          <ul aria-live="polite" className="divide-y divide-border">
            {rows.length === 0 ? (
              <li className="py-8 text-center text-muted-foreground">{t("empty")}</li>
            ) : (
              rows.map((row) => (
                <li key={row.id} className="flex min-h-11 items-center gap-3 py-2">
                  <span className="w-6 tabular-nums text-muted-foreground">{row.sequence}</span>
                  <span className="flex-1 font-medium">{row.display_name}</span>
                  <span className="tabular-nums text-muted-foreground">{row.phn_fragment}</span>
                  <Badge variant={row.source === "face" ? "pass" : "neutral"}>
                    {t(`row.${row.source}`)}
                  </Badge>
                  {row.needs_manual_verification ? (
                    <Badge variant="warn">{t("row.needsVerification")}</Badge>
                  ) : null}
                </li>
              ))
            )}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
