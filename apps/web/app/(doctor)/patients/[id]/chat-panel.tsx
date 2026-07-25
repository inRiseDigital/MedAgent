"use client";

/*
 * Conversational agent panel (06 §6, FR-2.6/3.x). Streams a cited answer from
 * the agent (via the BFF /api/chat), rendering the reply as markdown with
 * citation chips and staged prescription sign-off cards. Custom lightweight
 * reader over the AI SDK data-protocol frames (text-delta / data-citations /
 * data-proposals / finish).
 */
import { useCallback, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";
import { Sparkles, User } from "lucide-react";
import { Badge, Button, Spinner, type BadgeProps } from "@medagent/ui";

// Markdown rendering is loaded as a separate client-only chunk: it must NEVER
// be able to break the chat's core interactivity (send / input) if the markdown
// library fails to load. Falls back to plain text while loading / on failure.
const AssistantMarkdown = dynamic(
  () => import("@/components/markdown").then((m) => m.AssistantMarkdown),
  { ssr: false, loading: () => null },
);

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
    <div className="flex h-[34rem] flex-col gap-3">
      <div ref={logRef} role="log" aria-live="polite" className="flex-1 space-y-4 overflow-y-auto pr-1">
        {turns.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10 text-primary">
              <Sparkles className="h-5 w-5" />
            </span>
            <p className="max-w-sm text-sm text-muted-foreground">{t("chatIntro")}</p>
            <div className="flex flex-wrap justify-center gap-2">
              {QUICK_PROMPTS.map((p) => (
                <button
                  key={p}
                  onClick={() => void send(p)}
                  className="rounded-full border border-border bg-card px-3 py-1.5 text-xs text-foreground transition-colors hover:border-primary hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        ) : (
          turns.map((turn, i) =>
            turn.role === "user" ? (
              <div key={i} className="flex justify-end gap-2">
                <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-3.5 py-2 text-sm text-primary-foreground">
                  {turn.text}
                </div>
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
                  <User className="h-4 w-4" />
                </span>
              </div>
            ) : (
              <div key={i} className="flex gap-2">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                  <Sparkles className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="rounded-2xl rounded-tl-sm border border-border bg-card px-3.5 py-2.5">
                    {turn.text ? (
                      <AssistantMarkdown text={turn.text} />
                    ) : turn.streaming ? (
                      <span className="inline-flex items-center gap-2 text-sm text-muted-foreground">
                        <Spinner label={t("chatSending")} size="sm" /> {t("chatSending")}
                      </span>
                    ) : null}
                    {turn.streaming && turn.text ? (
                      <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-primary align-text-bottom" />
                    ) : null}
                    {turn.citations && turn.citations.length > 0 ? (
                      <div className="mt-2.5 flex flex-wrap items-center gap-1 border-t border-border pt-2">
                        <span className="mr-0.5 text-[0.7rem] font-medium text-muted-foreground">Sources</span>
                        {turn.citations.map((c) => (
                          <span
                            key={c.ref}
                            className="rounded border border-border bg-muted px-1.5 py-0.5 text-[0.7rem] font-medium text-muted-foreground"
                          >
                            {c.ref}
                          </span>
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
                        const blocked = p.verdict === "block";
                        return (
                          <div
                            key={key}
                            className={`rounded-lg border p-3 text-sm ${
                              blocked ? "border-destructive/40 bg-destructive-surface" : "border-border bg-card"
                            }`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-medium">
                                {t("proposalTitle")}: {p.drug} {p.dose_text}
                              </span>
                              <Badge variant={VERDICT_VARIANT[p.verdict]}>{p.verdict}</Badge>
                            </div>
                            {p.codes.length > 0 ? (
                              <p className="mt-1 text-xs text-muted-foreground">{p.codes.join(" · ")}</p>
                            ) : null}
                            <div className="mt-2.5 flex flex-wrap items-center gap-2">
                              <Button
                                size="sm"
                                onClick={() => void signProposal(key, p)}
                                disabled={blocked || state === "signing" || committed}
                              >
                                {state === "signing" ? t("chatSending") : t("proposalSign")}
                              </Button>
                              {committed ? (
                                <span className="text-xs font-medium text-success">
                                  {t("proposalSigned", { ref: state!.slice("committed:".length) })}
                                </span>
                              ) : null}
                              {blocked ? (
                                <span className="text-xs font-medium text-destructive">{t("proposalBlocked")}</span>
                              ) : null}
                              {state === "override" ? (
                                <span className="text-xs text-warning">{t("proposalOverride")}</span>
                              ) : null}
                              {state === "error" ? (
                                <span className="text-xs text-destructive">{t("proposalSignError")}</span>
                              ) : null}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                </div>
              </div>
            ),
          )
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
        className="flex gap-2 border-t border-border pt-3"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={t("chatPrompt")}
          aria-label={t("chatPrompt")}
          className="flex-1 rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <Button type="submit" disabled={busy || !input.trim()}>
          {busy ? t("chatSending") : t("chatSend")}
        </Button>
      </form>
    </div>
  );
}
