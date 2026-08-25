import { afterEach, describe, expect, it, vi } from "vitest";

import { type AgentEvent, streamAgentChat } from "@/lib/agent-stream";

/** Build a fake /api/chat Response whose body streams the given raw chunks. */
function sseResponse(chunks: string[], ok = true): Response {
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
  return { ok, body } as unknown as Response;
}

afterEach(() => vi.restoreAllMocks());

describe("streamAgentChat", () => {
  it("parses data frames in order and returns ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse([
      'data: {"type":"text-delta","delta":"Hel"}\n',
      'data: {"type":"text-delta","delta":"lo"}\n',
      'data: {"type":"data-citations","data":[{"ref":"Condition/1"}]}\n',
      "data: [DONE]\n",
    ])));
    const events: AgentEvent[] = [];
    const res = await streamAgentChat({ q: 1 }, { onEvent: (e) => events.push(e) });
    expect(res.ok).toBe(true);
    const text = events.filter((e) => e.type === "text-delta").map((e) => e.delta).join("");
    expect(text).toBe("Hello");
    expect(events.at(-1)).toEqual({ type: "data-citations", data: [{ ref: "Condition/1" }] });
  });

  it("reassembles a frame split across chunk boundaries", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse([
      'data: {"type":"text-delta","de',
      'lta":"Hi"}\n',
    ])));
    const events: AgentEvent[] = [];
    await streamAgentChat({}, { onEvent: (e) => events.push(e) });
    expect(events).toEqual([{ type: "text-delta", delta: "Hi" }]);
  });

  it("ignores [DONE], blank lines and malformed keep-alive frames", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse([
      "\n",
      "data: [DONE]\n",
      "data: not-json\n",
      ': comment\n',
      'data: {"type":"text-delta","delta":"ok"}\n',
    ])));
    const events: AgentEvent[] = [];
    await streamAgentChat({}, { onEvent: (e) => events.push(e) });
    expect(events).toEqual([{ type: "text-delta", delta: "ok" }]);
  });

  it("returns ok:false without reading a non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, body: null } as unknown as Response));
    const onEvent = vi.fn();
    const res = await streamAgentChat({}, { onEvent });
    expect(res.ok).toBe(false);
    expect(onEvent).not.toHaveBeenCalled();
  });

  it("forwards the abort signal to fetch", async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseResponse(["data: [DONE]\n"]));
    vi.stubGlobal("fetch", fetchMock);
    const ctrl = new AbortController();
    await streamAgentChat({ a: 1 }, { onEvent: () => {}, signal: ctrl.signal });
    expect(fetchMock).toHaveBeenCalledWith("/api/chat", expect.objectContaining({ signal: ctrl.signal }));
  });
});
