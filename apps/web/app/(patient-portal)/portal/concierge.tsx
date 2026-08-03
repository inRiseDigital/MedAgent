"use client";
/*
 * Patient concierge (FR-3, 07 §6) — the chat-first home. Streams the live agent
 * over the BFF SSE (/api/chat) about the signed-in patient's OWN record. Premium
 * bubbles, a warm welcome, and starter suggestions. Patient-toned; no clinician
 * sign-off UI. Tokens never touch the browser (the BFF attaches them).
 */
import { useCallback, useRef, useState } from "react";
import { Send, Sparkles } from "lucide-react";

type Turn = { role: "user" | "assistant"; text: string; streaming?: boolean };

const STARTERS = [
  "Summarise my record",
  "Any allergies I should know about?",
  "Explain my latest result",
  "What am I due for?",
];

export function Concierge({ patientPhn, name }: { patientPhn: string; name: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const scrollDown = useCallback(() => {
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }, []);

  const send = useCallback(
    async (q: string) => {
      const question = q.trim();
      if (!question || busy) return;
      setInput("");
      setBusy(true);
      const history: Turn[] = [...turns, { role: "user", text: question }];
      setTurns([...history, { role: "assistant", text: "", streaming: true }]);
      scrollDown();
      const patchLast = (fn: (t: Turn) => Turn) => setTurns((cur) => cur.map((t, i) => (i === cur.length - 1 ? fn(t) : t)));
      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ patient_id: patientPhn, messages: history.map((t) => ({ role: t.role, content: t.text })) }),
        });
        if (!res.ok || !res.body) {
          patchLast((t) => ({ ...t, text: "Sorry — the assistant is unavailable right now.", streaming: false }));
          return;
        }
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
              const o = JSON.parse(payload) as { type?: string; delta?: string };
              if (o.type === "text-delta" && o.delta) {
                patchLast((t) => ({ ...t, text: t.text + o.delta }));
                scrollDown();
              }
            } catch {
              /* ignore keep-alive / non-JSON frames */
            }
          }
        }
      } catch {
        patchLast((t) => ({ ...t, text: "Sorry — something went wrong. Please try again.", streaming: false }));
      } finally {
        setBusy(false);
        setTurns((cur) => cur.map((t, i) => (i === cur.length - 1 ? { ...t, streaming: false } : t)));
        scrollDown();
      }
    },
    [busy, turns, patientPhn, scrollDown],
  );

  return (
    <div className="flex h-[calc(100dvh-12rem)] flex-col overflow-hidden rounded-3xl border border-border bg-card shadow-sm">
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {/* welcome */}
        <div className="flex items-end gap-2">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <Sparkles className="h-4 w-4" />
          </span>
          <div className="rounded-2xl rounded-bl-md bg-muted/60 px-3.5 py-2.5 text-sm leading-relaxed">
            Hi {name.split(" ")[0]} 🌿 I&apos;m your health concierge. I can explain your results, your medicines, and what you&apos;re due for — grounded in your record. What would you like to know?
          </div>
        </div>

        {turns.map((t, i) =>
          t.role === "assistant" ? (
            <div key={i} className="flex items-end gap-2">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                <Sparkles className="h-4 w-4" />
              </span>
              <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-bl-md bg-muted/60 px-3.5 py-2.5 text-sm leading-relaxed">
                {t.text || (t.streaming ? "…" : "")}
              </div>
            </div>
          ) : (
            <div key={i} className="flex justify-end">
              <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-primary px-3.5 py-2.5 text-sm leading-relaxed text-primary-foreground">
                {t.text}
              </div>
            </div>
          ),
        )}

        {turns.length === 0 ? (
          <div className="flex flex-wrap gap-2 pt-1">
            {STARTERS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => void send(s)}
                className="rounded-full border border-primary/30 bg-background px-3 py-2 text-xs font-semibold text-primary shadow-sm transition-colors hover:bg-primary/5"
              >
                {s}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
        className="flex items-center gap-2 border-t border-border p-2.5"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about your health…"
          aria-label="Ask about your health"
          className="flex-1 rounded-full border border-border bg-background px-4 py-2.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          aria-label="Send"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition disabled:opacity-40"
        >
          <Send className="h-5 w-5" />
        </button>
      </form>
    </div>
  );
}
