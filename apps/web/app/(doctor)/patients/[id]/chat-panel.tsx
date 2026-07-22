"use client";

/*
 * Conversational agent panel (06 §6, FR-2.6/3.x). Streams a cited answer from
 * the agent (via the BFF /api/chat) and renders text + citation chips. Custom
 * lightweight streaming reader over the AI SDK data-protocol frames the
 * agent-service emits (text-delta / data-citations / finish).
 */
import { useCallback, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Badge, Button } from "@medagent/ui";

interface Citation {
  ref: string;
  resource_type?: string;
  id?: string;
}
interface Proposal {
  kind: string;
  drug?: string;
  dose_text?: string;
  verdict: "pass" | "warn" | "block";
  codes: string[];
}
interface Turn {
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
  proposals?: Proposal[];
  streaming?: boolean;
}

const VERDICT_VARIANT: Record<string, BadgeProps["variant"]> = {
  pass: "pass",
  warn: "warn",
  block: "block",
};

const QUICK_PROMPTS = [
  "Summarise this patient's active problems and medications.",
  "Any allergies or interaction concerns before prescribing?",
  "What are the most recent vital signs?",
];

export function ChatPanel({ patientId }: { patientId: string }) {
  const t = useTranslations("patient");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [signState, setSignState] = useState<Record<string, string>>({});
  const logRef = useRef<HTMLDivElement>(null);

  async function signProposal(key: string, p: Proposal) {
    setSignState((s) => ({ ...s, [key]: "signing" }));
    try {
      const res = await fetch("/api/proposals/commit", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          kind: "prescription",
          patient: patientId,
          payload: { drug: p.drug, dose_text: p.dose_text },
        }),
      });
      const data = (await res.json()) as { committed?: string };
      if (res.status === 201 && data.committed) {
        setSignState((s) => ({ ...s, [key]: `committed:${data.committed}` }));
      } else if (res.status === 422) {
        setSignState((s) => ({ ...s, [key]: "override" }));
      } else {
        setSignState((s) => ({ ...s, [key]: "error" }));
      }
    } catch {
      setSignState((s) => ({ ...s, [key]: "error" }));
    }
  }

  const send = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q || busy) return;
      setInput("");
      setBusy(true);
      const history: Turn[] = [...turns, { role: "user", text: q }];
      setTurns([...history, { role: "assistant", text: "", streaming: true }]);

      const patch = (fn: (a: Turn) => Turn) =>
        setTurns((prev) => {
          const next = [...prev];
          const i = next.length - 1;
          if (i >= 0 && next[i]!.role === "assistant") next[i] = fn(next[i]!);
          return next;
        });

      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            patient_id: patientId,
            messages: history.map((m) => ({ role: m.role, content: m.text })),
          }),
        });
        if (!res.ok || !res.body) {
          patch((a) => ({ ...a, text: t("chatError"), streaming: false }));
          return;
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const payload = line.slice(6).trim();
            if (!payload || payload === "[DONE]") continue;
            let evt: Record<string, unknown>;
            try {
              evt = JSON.parse(payload);
            } catch {
              continue;
            }
            if (evt.type === "text-delta" && typeof evt.delta === "string") {
              const delta = evt.delta;
              patch((a) => ({ ...a, text: a.text + delta }));
              logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
            } else if (evt.type === "data-citations" && Array.isArray(evt.data)) {
              patch((a) => ({ ...a, citations: evt.data as Citation[] }));
            } else if (evt.type === "data-proposals" && Array.isArray(evt.data)) {
              patch((a) => ({ ...a, proposals: evt.data as Proposal[] }));
            }
          }
        }
        patch((a) => ({ ...a, streaming: false }));
      } catch {
        patch((a) => ({ ...a, text: t("chatError"), streaming: false }));
      } finally {
        setBusy(false);
      }
    },
    [busy, patientId, t, turns],
  );

  return (
    <div className="flex h-[32rem] flex-col gap-3">
      <div
        ref={logRef}
        role="log"
        aria-live="polite"
        className="flex-1 space-y-3 overflow-y-auto rounded-md border border-border bg-background p-3"
      >
        {turns.length === 0 ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">{t("chatIntro")}</p>
            <div className="flex flex-wrap gap-2">
              {QUICK_PROMPTS.map((p) => (
                <button
                  key={p}
                  onClick={() => void send(p)}
                  className="rounded-full border border-border bg-card px-3 py-1 text-2xs text-foreground hover:border-primary focus-visible:outline-2 focus-visible:outline-ring"
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        ) : (
          turns.map((turn, i) => (
            <div key={i} className={turn.role === "user" ? "text-right" : ""}>
              <div
                className={
                  turn.role === "user"
                    ? "inline-block rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground"
                    : "inline-block max-w-full rounded-lg bg-muted px-3 py-2 text-sm text-foreground"
                }
              >
                <p className="whitespace-pre-wrap">
                  {turn.text}
                  {turn.streaming ? <span className="animate-pulse"> ▌</span> : null}
                </p>
                {turn.citations && turn.citations.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-1 border-t border-border pt-2">
                    {turn.citations.map((c) => (
                      <Badge key={c.ref} variant="neutral">
                        {c.ref}
                      </Badge>
                    ))}
                  </div>
                ) : null}
              </div>
              {turn.proposals && turn.proposals.length > 0 ? (
                <div className="mt-2 space-y-2">
                  {turn.proposals.map((p, pi) => {
                    const key = `${i}:${pi}`;
                    const state = signState[key];
                    const committed = state?.startsWith("committed:");
                    return (
                      <div key={key} className="rounded-md border border-border bg-card p-3 text-sm">
                        <div className="flex items-center gap-2">
                          <Badge variant={VERDICT_VARIANT[p.verdict]}>{p.verdict}</Badge>
                          <span className="font-medium">Rx: {p.drug} {p.dose_text}</span>
                        </div>
                        {p.codes.length > 0 ? (
                          <p className="mt-1 text-2xs text-muted-foreground">{p.codes.join(", ")}</p>
                        ) : null}
                        <div className="mt-2 flex items-center gap-2">
                          <Button
                            size="sm"
                            onClick={() => void signProposal(key, p)}
                            disabled={p.verdict === "block" || state === "signing" || committed}
                          >
                            {t("proposalSign")}
                          </Button>
                          {committed ? (
                            <span className="text-2xs text-success">
                              {t("proposalSigned", { ref: state!.slice("committed:".length) })}
                            </span>
                          ) : null}
                          {p.verdict === "block" ? (
                            <span className="text-2xs text-destructive">{t("proposalBlocked")}</span>
                          ) : null}
                          {state === "override" ? (
                            <span className="text-2xs text-warning">{t("proposalOverride")}</span>
                          ) : null}
                          {state === "error" ? (
                            <span className="text-2xs text-destructive">{t("proposalSignError")}</span>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </div>
          ))
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
        className="flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={t("chatPrompt")}
          aria-label={t("chatPrompt")}
          className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring"
        />
        <Button type="submit" disabled={busy || !input.trim()}>
          {busy ? t("chatSending") : t("chatSend")}
        </Button>
      </form>
    </div>
  );
}
