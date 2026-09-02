"use client";

/*
 * Conversational agent panel (06 §6, FR-2.6/3.x). Streams a cited answer from
 * the agent (via the BFF /api/chat), rendering the reply as markdown with
 * citation chips and staged prescription sign-off cards. Custom lightweight
 * reader over the AI SDK data-protocol frames (text-delta / data-citations /
 * data-proposals / finish).
 */
import { useCallback, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";
import { Send, Sparkles } from "lucide-react";
import { Badge, Button, type BadgeProps } from "@medagent/ui";

import { VoiceButton } from "@/components/voice-button";
import { streamAgentChat } from "@/lib/agent-stream";
import { Widget, type WidgetSpec } from "@/components/widgets";

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
  widgets?: WidgetSpec[];
  status?: string;
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

interface OpeningBrief {
  greeting: string;
  flags: { severity: string; text: string }[];
  ambient: string;
}

export function ChatPanel({ patientId, opening }: { patientId: string; opening?: OpeningBrief }) {
  const t = useTranslations("patient");
  // Stable conversation id (H0-S1) — the server owns the thread keyed by this, so the
  // copilot conversation survives a reload. Persisted per patient.
  const convId = useMemo(() => {
    try {
      const k = `md:conv:${patientId}`;
      let v = localStorage.getItem(k);
      if (!v) { v = crypto.randomUUID?.() ?? `c-${Date.now()}-${Math.random().toString(36).slice(2)}`; localStorage.setItem(k, v); }
      return v;
    } catch { return `conv-${patientId}`; }
  }, [patientId]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [signState, setSignState] = useState<Record<string, string>>({});
  const logRef = useRef<HTMLDivElement>(null);
  const consultItems = useRef<Record<string, string>>({}); // agenda id → label, for the session summary

  // Consult session (H1): fetch a grounded agenda and render it as a checklist the
  // doctor confirms item by item; "Complete" drafts a session note from the
  // confirmed items (a draft for the doctor to review and sign — never auto-filed).
  async function startConsult() {
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch("/api/consult/agenda", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ patient_id: patientId }),
      });
      const data = res.ok ? ((await res.json()) as { items?: { id: string; label: string }[] }) : { items: [] };
      const items = data.items ?? [];
      consultItems.current = Object.fromEntries(items.map((i) => [i.id, i.label]));
      setTurns((prev) => [...prev, {
        role: "assistant",
        text: "Here's the consultation agenda, grounded in the chart. Confirm each item as you address it, then complete the session to draft a note.",
        widgets: [{ id: "consult", kind: "consult-session", title: "Consultation", data: { items } }],
      }]);
    } catch {
      setTurns((prev) => [...prev, { role: "assistant", text: t("chatError") }]);
    } finally {
      setBusy(false);
    }
  }

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
        const result = await streamAgentChat(
          { patient_id: patientId, conversation_id: convId, messages: history.map((m) => ({ role: m.role, content: m.text })) },
          {
            onEvent: (evt) => {
              if (evt.type === "text-delta" && typeof evt.delta === "string") {
                const delta = evt.delta;
                patch((a) => ({ ...a, text: a.text + delta, status: undefined }));
                logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
              } else if (evt.type === "data-status" && typeof evt.text === "string") {
                patch((a) => ({ ...a, status: evt.text }));
                logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
              } else if (evt.type === "data-citations" && Array.isArray(evt.data)) {
                patch((a) => ({ ...a, citations: evt.data as Citation[] }));
              } else if (evt.type === "data-proposals" && Array.isArray(evt.data)) {
                patch((a) => ({ ...a, proposals: evt.data as Proposal[] }));
              } else if (evt.type === "data-widget" && evt.widget) {
                patch((a) => ({ ...a, widgets: [...(a.widgets ?? []), evt.widget as WidgetSpec] }));
              }
            },
          },
        );
        if (!result.ok) {
          patch((a) => ({ ...a, text: t("chatError"), streaming: false }));
          return;
        }
        // Never settle on a silent blank bubble: the server floors an answer, but
        // if no text arrived at all, show a retry line instead of rendering null.
        patch((a) => ({ ...a, streaming: false, text: a.text || t("chatError") }));
      } catch {
        patch((a) => ({ ...a, text: t("chatError"), streaming: false }));
      } finally {
        setBusy(false);
      }
    },
    [busy, patientId, t, turns, convId],
  );

  const flagCls = (sev: string) =>
    sev === "block"
      ? "border-destructive/40 bg-destructive-surface text-destructive"
      : sev === "warn"
        ? "border-warning/40 bg-warning-surface text-warning"
        : "border-border bg-muted text-foreground";

  return (
    <div className="flex min-h-[24rem] flex-1 flex-col bg-background">
      <div ref={logRef} role="log" aria-live="polite" className="flex flex-1 flex-col gap-3 overflow-y-auto p-3.5">
        {/* Copilot opening — proactive safety brief (real flags + ambient summary) */}
        {opening ? (
          <>
            <div className="mh-msg ai"><div className="mh-ai-row"><span className="mh-av"><Sparkles className="h-4 w-4" /></span><div className="mh-bubble">{opening.greeting}</div></div></div>
            {opening.flags.length > 0 ? (
              <div className="mh-msg ai" style={{ maxWidth: "94%" }}>
                <div className="mh-ai-row">
                  <span className="mh-av" />
                  <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                    {opening.flags.map((f, i) => (
                      <div key={i} className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-xs font-semibold ${flagCls(f.severity)}`}><span aria-hidden>⚠</span><span>{f.text}</span></div>
                    ))}
                  </div>
                </div>
              </div>
            ) : null}
            <div className="mh-msg ai"><div className="mh-ai-row"><span className="mh-av"><Sparkles className="h-4 w-4" /></span><div className="mh-bubble" style={{ color: "var(--mh-ink-2)" }}>{opening.ambient}</div></div></div>
          </>
        ) : null}

        {turns.length === 0 && !opening ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <span className="mh-av" style={{ width: 40, height: 40 }}><Sparkles className="h-5 w-5" /></span>
            <p className="max-w-sm text-sm text-muted-foreground">{t("chatIntro")}</p>
          </div>
        ) : null}

        {turns.map((turn, i) =>
          turn.role === "user" ? (
            <div key={i} className="mh-msg me"><div className="mh-bubble">{turn.text}</div></div>
          ) : (
            <div key={i} className="mh-msg ai" style={{ maxWidth: turn.proposals && turn.proposals.length ? "96%" : undefined }}>
              <div className="mh-ai-row">
                <span className="mh-av"><Sparkles className="h-4 w-4" /></span>
                <div className="min-w-0 flex-1">
                  {!turn.text && turn.streaming && turn.status ? (
                    <div className="mh-think" aria-live="polite"><Sparkles className="h-3.5 w-3.5" /><span>{turn.status}</span><i /><i /><i /></div>
                  ) : (
                  <div className="mh-bubble">
                    {turn.text ? <AssistantMarkdown text={turn.text} /> : turn.streaming ? <span className="mh-typing"><i /><i /><i /></span> : null}
                    {turn.citations && turn.citations.length > 0 ? (
                      <div className="mh-srcs">
                        <span className="mh-srcs-lbl">✓ Grounded in the chart</span>
                        {turn.citations.map((c) => (<span key={c.ref} className="mh-src">{c.resource_type ?? c.ref}</span>))}
                      </div>
                    ) : null}
                  </div>
                  )}

                  {turn.proposals && turn.proposals.length > 0 ? (
                    <div className="mt-2 space-y-2">
                      {turn.proposals.map((p, pi) => {
                        const key = `${i}:${pi}`;
                        const state = signState[key];
                        const committed = state?.startsWith("committed:");
                        const blocked = p.verdict === "block";
                        return (
                          <div key={key} className={`rounded-2xl border p-3 text-sm shadow-sm ${blocked ? "border-destructive/40 bg-destructive-surface" : "border-border bg-card"}`}>
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-semibold">{t("proposalTitle")}: {p.drug} {p.dose_text}</span>
                              <Badge variant={VERDICT_VARIANT[p.verdict]}>{p.verdict}</Badge>
                            </div>
                            {p.codes.length > 0 ? <p className="mt-1 text-xs text-muted-foreground">{p.codes.join(" · ")}</p> : null}
                            <div className="mt-2.5 flex flex-wrap items-center gap-2">
                              <Button size="sm" onClick={() => void signProposal(key, p)} disabled={blocked || state === "signing" || committed}>
                                {state === "signing" ? t("chatSending") : t("proposalSign")}
                              </Button>
                              {committed ? <span className="text-xs font-medium text-success">{t("proposalSigned", { ref: state!.slice("committed:".length) })}</span> : null}
                              {blocked ? <span className="text-xs font-medium text-destructive">{t("proposalBlocked")}</span> : null}
                              {state === "override" ? <span className="text-xs text-warning">{t("proposalOverride")}</span> : null}
                              {state === "error" ? <span className="text-xs text-destructive">{t("proposalSignError")}</span> : null}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}

                  {turn.widgets && turn.widgets.length > 0 ? (
                    <div className="mt-2 flex flex-col gap-2">
                      {turn.widgets.map((w) => (
                        <Widget key={w.id} spec={w}
                          onAction={(id) => void send(id.includes("/") ? `Tell me about ${id}` : id)}
                          onConfirm={async (action, params) => {
                            if (action === "consult-complete") {
                              // Sign & file (S7): the confirmed items become a real,
                              // gated FHIR Encounter + note. The doctor confirmed each
                              // item — Complete is the deliberate sign-off.
                              const ids = Array.isArray(params.confirmed) ? (params.confirmed as string[]) : [];
                              const labels = ids.map((id) => consultItems.current[id]).filter(Boolean);
                              try {
                                const res = await fetch("/api/consult/commit", {
                                  method: "POST", headers: { "content-type": "application/json" },
                                  body: JSON.stringify({ patient_id: patientId, items: labels }),
                                });
                                if (!res.ok) return false;
                                const d = (await res.json()) as { encounter_id?: string };
                                setTurns((prev) => [...prev, {
                                  role: "assistant", text: "",
                                  widgets: [{ id: `consult-receipt-${Date.now()}`, kind: "summary", title: "Consultation filed", data: {
                                    tone: "good",
                                    points: [
                                      d.encounter_id ? `Encounter recorded — ${d.encounter_id}` : "Encounter recorded",
                                      `${labels.length} item(s) documented to the note`,
                                      "Filed to the patient's record",
                                    ],
                                  } }],
                                }]);
                                return true;
                              } catch {
                                return false;
                              }
                            }
                            return false;
                          }} />
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          ),
        )}
      </div>

      {/* quick-reply chips — before any turn; lead with the consult session (H1) */}
      {turns.length === 0 ? (
        <div className="mh-quick">
          <button type="button" className="mh-chip" onClick={() => void startConsult()}
            style={{ color: "var(--primary-foreground)", background: "var(--primary)" }}>
            🩺 Start consult session
          </button>
          {QUICK_PROMPTS.map((p) => (<button key={p} type="button" className="mh-chip" onClick={() => void send(p)}>{p}</button>))}
        </div>
      ) : null}

      <form className="mh-composer" onSubmit={(e) => { e.preventDefault(); void send(input); }}>
        <VoiceButton
          title="Voice command — say 'give summary'"
          onTranscript={(tx) => {
            if (/\b(summary|brief)\b/i.test(tx)) {
              void send("Give me a concise, cited summary of this patient — active problems, current medications, allergies, and recent results.");
            } else {
              setInput((prev) => (prev ? `${prev} ${tx}` : tx));
            }
          }}
        />
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder={t("chatPrompt")} aria-label={t("chatPrompt")} />
        <button type="submit" className="mh-circ send" disabled={busy || !input.trim()} aria-label={t("chatSend")}><Send className="h-5 w-5" /></button>
      </form>
    </div>
  );
}
