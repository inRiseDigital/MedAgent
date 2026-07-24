/*
 * SSE client — EventSource wrapper with the single-use ticket handoff of
 * docs/solution/02 §11 (ADR I-10) and real reconnect/backoff + connection
 * state (06 §3 FR-2.1: the prototype's decorative "Listening…" pulse is
 * replaced by actual EventSource health).
 *
 * Flow per connection attempt:
 * 1. POST to the cookie-authenticated BFF ticket endpoint. The BFF holds
 *    the session's bearer token server-side and obtains a single-use,
 *    30-second, opaque Redis ticket from notify-service's issuance endpoint
 *    (POST /notify/ticket — notify-service owns the full ticket lifecycle,
 *    02 §11) — native EventSource cannot set an Authorization header, and
 *    bearer tokens never appear in URLs.
 * 2. Open GET {stream}?ticket={id} directly against notify-service.
 *    The ticket is redeemed atomically (GETDEL) — replay gets 401.
 * 3. On error/close (including the server's 15-min max stream age), fetch
 *    a FRESH ticket and reconnect with exponential backoff + jitter.
 *
 * The BFF ticket route (/api/sse/ticket) and notify-service issuance
 * (POST /notify/ticket) now exist; this wrapper is what the queue page wires
 * against. Live end-to-end wiring to the queue UI lands in S3 (06 §3).
 */

export type ConnectionState = "connecting" | "open" | "reconnecting" | "closed" | "unauthorized";

export interface SseEvent {
  /** SSE `event:` name ("message" when unnamed). */
  type: string;
  /** Raw `data:` payload — callers parse (JSON events per 01 §1). */
  data: string;
}

export interface EventStreamOptions {
  /** Cookie-authenticated BFF endpoint that returns { ticket: string }. */
  ticketUrl?: string;
  /** notify-service stream endpoint (NEXT_PUBLIC_NOTIFY_STREAM_URL). */
  streamUrl?: string;
  /** Named SSE events to listen for, besides the default "message". */
  eventTypes?: string[];
  onEvent: (event: SseEvent) => void;
  /** Drives the real connection-state indicator + degraded-mode banner (06 §10). */
  onStateChange?: (state: ConnectionState) => void;
  baseRetryDelayMs?: number;
  maxRetryDelayMs?: number;
}

export interface EventStreamHandle {
  close: () => void;
}

/** Exponential backoff with full jitter, clamped to [base, max]. */
export function computeBackoffDelay(
  attempt: number,
  baseMs = 1_000,
  maxMs = 30_000,
): number {
  const exp = Math.min(maxMs, baseMs * 2 ** Math.max(0, attempt));
  return baseMs + Math.random() * Math.max(0, exp - baseMs);
}

export function createEventStream(options: EventStreamOptions): EventStreamHandle {
  const ticketUrl = options.ticketUrl ?? "/api/sse/ticket";
  const streamUrl =
    options.streamUrl ?? process.env.NEXT_PUBLIC_NOTIFY_STREAM_URL ?? "/notify/stream";

  let source: EventSource | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let attempt = 0;
  let closed = false;

  const setState = (state: ConnectionState) => {
    if (!closed || state === "closed") options.onStateChange?.(state);
  };

  async function connect(): Promise<void> {
    if (closed) return;
    setState(attempt === 0 ? "connecting" : "reconnecting");

    let ticket: string;
    try {
      // Same-origin, session-cookie-authenticated; never a bearer token.
      const res = await fetch(ticketUrl, { method: "POST" });
      // 401 = the session is gone (expired/idle-timeout). Retrying is futile and
      // just spams the console — stop and surface a terminal state so the UI can
      // prompt re-login (02 §4: 30-min idle timeout is a deliberate control).
      if (res.status === 401) {
        closed = true;
        options.onStateChange?.("unauthorized");
        return;
      }
      if (!res.ok) throw new Error(`ticket endpoint returned ${res.status}`);
      ({ ticket } = (await res.json()) as { ticket: string });
    } catch {
      scheduleReconnect();
      return;
    }
    if (closed) return;

    // The opaque single-use ticket is the ONE deliberate query-string
    // credential (dead after first redemption, log-scrubbed — 02 ADR I-10).
    const url = new URL(streamUrl, window.location.origin);
    url.searchParams.set("ticket", ticket);
    source = new EventSource(url);

    source.onopen = () => {
      attempt = 0;
      setState("open");
    };
    source.onerror = () => {
      // Covers network drops AND the server-enforced 15-min max stream age;
      // either way the old ticket is spent, so reconnect via a fresh one.
      source?.close();
      source = null;
      scheduleReconnect();
    };
    source.onmessage = (ev) => options.onEvent({ type: "message", data: ev.data });
    for (const type of options.eventTypes ?? []) {
      source.addEventListener(type, (ev) =>
        options.onEvent({ type, data: (ev as MessageEvent<string>).data }),
      );
    }
  }

  function scheduleReconnect(): void {
    if (closed) return;
    setState("reconnecting");
    const delay = computeBackoffDelay(
      attempt++,
      options.baseRetryDelayMs,
      options.maxRetryDelayMs,
    );
    retryTimer = setTimeout(() => void connect(), delay);
  }

  void connect();

  return {
    close: () => {
      closed = true;
      if (retryTimer) clearTimeout(retryTimer);
      source?.close();
      source = null;
      setState("closed");
    },
  };
}
