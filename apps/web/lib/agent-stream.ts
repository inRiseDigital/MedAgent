/*
 * Shared agent chat transport (P4.2). The doctor workspace and the patient
 * concierge both streamed /api/chat by hand-rolling the same SSE reader — fetch,
 * getReader, TextDecoder, split on newlines, parse each `data:` frame. That loop
 * lived in two places and drifted. Centralise the transport + framing here; each
 * surface still owns its own state updates via the onEvent callback (a text-delta
 * appends text, data-citations/proposals/cards do surface-specific things).
 */

export interface AgentEvent {
  type?: string;
  delta?: string;
  data?: unknown;
}

export interface StreamHandlers {
  onEvent: (event: AgentEvent) => void;
  /** Optional abort signal (e.g. a client-side stall timeout). */
  signal?: AbortSignal;
}

/**
 * POST `body` to /api/chat and invoke `onEvent` for every SSE data frame until
 * the stream closes. Returns `{ ok: false }` when the response is not a readable
 * event-stream (the caller renders its own error); throws only if the caller's
 * signal aborts or the network fails, so callers keep their try/catch.
 */
export async function streamAgentChat(
  body: unknown,
  handlers: StreamHandlers,
): Promise<{ ok: boolean }> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal: handlers.signal,
  });
  if (!res.ok || !res.body) return { ok: false };

  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice(6).trim();
      if (!payload || payload === "[DONE]") continue;
      try {
        handlers.onEvent(JSON.parse(payload) as AgentEvent);
      } catch {
        /* keep-alive / partial frame — ignore */
      }
    }
  }
  return { ok: true };
}
