"use client";
/*
 * Patient concierge (FR-3, 07 §6) — the chat-first home, matching the approved
 * premium prototype exactly: proactive nudge cards, a services shelf, and a
 * conversational-commerce booking flow (clinician carousel → slot picker →
 * animated receipt → upsells). Free-text and "Explain my result" stream the LIVE
 * agent over the BFF SSE (/api/chat); the guided flows are scripted UX. Styling
 * comes from the `.mh` premium theme.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Bell,
  CalendarDays,
  FileText,
  MessageSquareText,
  Mic,
  Send,
  Sparkles,
  Syringe,
} from "lucide-react";

import { VideoRoom } from "@/components/video-room";

type Tone = "urgent" | "good" | "warn" | "info";
type Action = { label: string; kind?: "pri" | "ghost"; icon?: React.ReactNode; act: () => void };
type CardData = {
  tone: Tone;
  kicker?: string;
  title: string;
  text?: string;
  facts?: { t?: "good" | "warn" | "urgent"; x: string }[];
  cite?: string;
  actions?: Action[];
};
type Node =
  | { t: "ai"; text: string; streaming?: boolean; cites?: { ref: string; resource_type?: string }[] }
  | { t: "me"; text: string }
  | { t: "typing" }
  | { t: "card"; data: CardData }
  | { t: "services" }
  | { t: "bslots"; slots: BSlot[] }
  | { t: "breceipt"; b: BookResult };
type Quick = { label: string; act: () => void };
type BSlot = { id: string; start?: string; end?: string; specialty?: string; facility?: string };
type BookResult = { appointment_id?: string; start?: string; end?: string; specialty?: string; facility?: string };

const TONE_COLOR: Record<Tone, string> = { urgent: "var(--heart)", good: "var(--activity)", warn: "var(--nutri)", info: "var(--mh-tint)" };
const TONE_BG: Record<Tone, string> = { urgent: "var(--heart-bg)", good: "var(--activity-bg)", warn: "var(--nutri-bg)", info: "var(--body-bg)" };
const FACT_COLOR: Record<string, string> = { good: "var(--activity)", warn: "var(--nutri)", urgent: "var(--heart)" };

const dayLabel = (iso?: string) => (iso ? new Date(iso).toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" }) : "");
const timeLabel = (iso?: string) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "");
// Group real slots by calendar day for the picker.
function groupSlots(slots: BSlot[]): [string, BSlot[]][] {
  const by = new Map<string, BSlot[]>();
  for (const s of slots) {
    const k = dayLabel(s.start);
    const arr = by.get(k) ?? [];
    arr.push(s);
    by.set(k, arr);
  }
  return [...by.entries()];
}

// Lightweight markdown for agent answers — bold, inline code, bullet lists,
// headings, paragraphs. No external library (keeps the bundle small + CSP clean),
// matching the project's hand-rolled-primitives approach.
function renderInline(text: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /\*\*(.+?)\*\*|`([^`]+?)`/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] != null) out.push(<strong key={k++}>{m[1]}</strong>);
    else if (m[2] != null) out.push(<code key={k++} className="mh-code">{m[2]}</code>);
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
function FormattedText({ text }: { text: string }) {
  const blocks: React.ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (!bullets.length) return;
    const items = bullets;
    bullets = [];
    blocks.push(<ul key={`u${blocks.length}`}>{items.map((b, i) => <li key={i}>{renderInline(b)}</li>)}</ul>);
  };
  for (const ln of text.split("\n")) {
    const t = ln.trim();
    if (/^[-*•]\s+/.test(t)) { bullets.push(t.replace(/^[-*•]\s+/, "")); continue; }
    flush();
    if (!t) continue;
    if (/^#{1,4}\s+/.test(t)) { blocks.push(<p key={`h${blocks.length}`} className="mh-h">{renderInline(t.replace(/^#{1,4}\s+/, ""))}</p>); continue; }
    blocks.push(<p key={`p${blocks.length}`}>{renderInline(t)}</p>);
  }
  flush();
  return <div className="mh-rich">{blocks}</div>;
}

export type ConciergeSignals = {
  overdueVaccines: string[];
  latestResult: { text: string; conclusion?: string; critical: boolean; ref: string } | null;
  medsCount: number;
  medications: { text: string; ref: string }[];
  accessRecent: { title: string; when: string }[];
};

export function Concierge({ patientPhn, name, signals }: { patientPhn: string; name: string; signals: ConciergeSignals }) {
  const first = name.split(" ")[0] ?? "there";
  const locale = useLocale();
  const tnav = useTranslations("patientNav");
  const tc = useTranslations("concierge");
  const [msgs, setMsgs] = useState<Node[]>([]);
  const [quicks, setQuicks] = useState<Quick[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [inVideo, setInVideo] = useState(false);
  const [listening, setListening] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const ran = useRef(false);
  const videoRoom = `medagent-${patientPhn}`; // deterministic: doctor + patient meet here
  // Voice layer (free, browser Web Speech API). BCP-47 tag per UI locale.
  const bcp47 = locale === "si" ? "si-LK" : locale === "ta" ? "ta-LK" : "en-US";
  const recognitionRef = useRef<{ stop: () => void; start: () => void } | null>(null);
  const speakNextRef = useRef(false);
  const voicesRef = useRef<SpeechSynthesisVoice[]>([]);

  const down = useCallback(() => {
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }, []);
  const push = useCallback((n: Node) => { setMsgs((m) => [...m, n]); down(); }, [down]);
  const me = useCallback((text: string) => push({ t: "me", text }), [push]);
  const typing = useCallback(
    (cb: () => void, ms = 850) => {
      setMsgs((m) => [...m, { t: "typing" }]);
      down();
      window.setTimeout(() => {
        setMsgs((m) => m.filter((n) => n.t !== "typing"));
        cb();
      }, ms);
    },
    [down],
  );

  // ---- live agent (real, cited) for explain + free text ----
  const streamAgent = useCallback(
    async (question: string) => {
      if (busy) return;
      setBusy(true);
      const prior = msgs.filter((n): n is Extract<Node, { t: "ai" | "me" }> => n.t === "ai" || n.t === "me");
      const history = [...prior, { t: "me" as const, text: question }];
      setMsgs((m) => [...m, { t: "me", text: question }, { t: "ai", text: "", streaming: true }]);
      down();
      const bump = (fn: (t: Node & { t: "ai" }) => Node) =>
        setMsgs((m) => m.map((n, i) => (i === m.length - 1 && n.t === "ai" ? fn(n) : n)));
      let full = "";
      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            patient_id: patientPhn,
            audience: "patient",
            locale,
            messages: history.map((t) => ({ role: t.t === "me" ? "user" : "assistant", content: t.text })),
          }),
        });
        if (!res.ok || !res.body) {
          bump((n) => ({ ...n, text: "Sorry — the assistant is unavailable right now.", streaming: false }));
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
            const p = line.slice(6).trim();
            if (!p || p === "[DONE]") continue;
            try {
              const o = JSON.parse(p) as { type?: string; delta?: string; data?: unknown };
              if (o.type === "text-delta" && o.delta) { full += o.delta; bump((n) => ({ ...n, text: n.text + o.delta })); down(); }
              else if (o.type === "data-citations" && Array.isArray(o.data)) { const cites = o.data as { ref: string; resource_type?: string }[]; bump((n) => ({ ...n, cites })); down(); }
              else if (o.type === "data-cards" && Array.isArray(o.data)) {
                for (const c of o.data as { tone?: Tone; title?: string; points?: string[] }[]) {
                  if (!c.title) continue;
                  push({ t: "card", data: { tone: c.tone ?? "info", kicker: "Summary", title: c.title, facts: (c.points ?? []).map((x) => ({ x })) } });
                }
              }
            } catch { /* keep-alive */ }
          }
        }
      } catch {
        bump((n) => ({ ...n, text: "Sorry — something went wrong. Please try again.", streaming: false }));
      } finally {
        setBusy(false);
        setMsgs((m) => m.map((n, i) => (i === m.length - 1 && n.t === "ai" ? { ...n, streaming: false } : n)));
        down();
        if (speakNextRef.current) { speakNextRef.current = false; speak(full); }
      }
    },
    [busy, msgs, patientPhn, down, locale, bcp47],
  );

  // ---- scripted conversational-commerce flows ----
  const menu = useCallback((): Quick[] => [
    { label: tc("chipRefill"), act: () => refill() },
    { label: tc("chipBook"), act: () => book("a follow-up") },
    { label: tc("chipDue"), act: () => dueCheck() },
    { label: tc("chipVideo"), act: () => startVideo() },
    { label: tc("chipWho"), act: () => whoSaw() },
  ], []); // eslint-disable-line react-hooks/exhaustive-deps

  // Agent-first: every typed question goes to the LIVE patient-persona agent,
  // which reads the real FHIR record and answers with citations. Scripted flows
  // fire only from explicit card/chip taps (booking, refill, the greeting cards).
  function handleFree(text: string) {
    void streamAgent(text);
  }

  // --- voice layer (free, browser Web Speech API; locale-aware) ---
  // Prefer a natural/neural voice for the locale — the default synthesizer voice
  // is the robotic one. Quality neural voices (Edge "…Natural", Google, Apple
  // premium) carry these keywords.
  function pickVoice(): SpeechSynthesisVoice | undefined {
    const vs = voicesRef.current;
    if (!vs.length) return undefined;
    const want = [bcp47.toLowerCase(), locale.toLowerCase()];
    const matches = vs.filter((v) => want.some((w) => v.lang?.toLowerCase().startsWith(w)));
    const pool = matches.length ? matches : locale === "en" ? vs.filter((v) => v.lang?.toLowerCase().startsWith("en")) : [];
    const nice = /natural|neural|online|enhanced|premium|google|siri|aria|jenny|libby|sonia|nova|emma/i;
    return pool.find((v) => nice.test(v.name)) ?? pool[0] ?? vs.find((v) => nice.test(v.name));
  }
  function speak(text: string) {
    if (typeof window === "undefined" || !("speechSynthesis" in window) || !text.trim()) return;
    try {
      const u = new SpeechSynthesisUtterance(text.replace(/\[source:[^\]]*\]/g, "").replace(/[*_`#]/g, "").slice(0, 600));
      const v = pickVoice();
      if (v) { u.voice = v; u.lang = v.lang; } else { u.lang = bcp47; }
      u.rate = 0.97; // a touch slower = smoother, less clipped
      u.pitch = 1.0;
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(u);
    } catch {
      /* TTS unavailable — silently ignore */
    }
  }
  function toggleVoice() {
    if (listening) { recognitionRef.current?.stop(); return; }
    const SR = (window as unknown as { SpeechRecognition?: new () => unknown; webkitSpeechRecognition?: new () => unknown });
    const Ctor = SR.SpeechRecognition ?? SR.webkitSpeechRecognition;
    if (!Ctor) {
      push({ t: "ai", text: "Voice input isn't supported in this browser — try Chrome, or just type your question." });
      return;
    }
    const rec = new Ctor() as {
      lang: string; interimResults: boolean; maxAlternatives: number; start: () => void; stop: () => void;
      onresult: ((e: { results: { 0: { 0: { transcript: string } } } }) => void) | null;
      onend: (() => void) | null; onerror: (() => void) | null;
    };
    rec.lang = bcp47;
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = (e) => {
      const t = e.results?.[0]?.[0]?.transcript?.trim();
      if (t) { setInput(""); speakNextRef.current = true; handleFree(t); }
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recognitionRef.current = rec;
    setListening(true);
    rec.start();
  }

  // Record/Summary rows dispatch "mh:ask" to have the concierge answer about an
  // item. Keep a ref to the latest handler so the once-registered listener never
  // goes stale.
  const askRef = useRef<(q: string) => void>(() => {});
  askRef.current = handleFree;
  useEffect(() => {
    const handler = (e: Event) => {
      const q = (e as CustomEvent).detail;
      if (typeof q === "string" && q.trim()) askRef.current(q);
    };
    window.addEventListener("mh:ask", handler);
    return () => window.removeEventListener("mh:ask", handler);
  }, []);

  // Speech-synthesis voices load asynchronously; cache them so `speak` can pick
  // the best neural voice rather than falling back to the robotic default.
  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const load = () => { voicesRef.current = window.speechSynthesis.getVoices(); };
    load();
    window.speechSynthesis.addEventListener?.("voiceschanged", load);
    return () => window.speechSynthesis.removeEventListener?.("voiceschanged", load);
  }, []);

  // REAL: ask the live patient-persona agent to explain the patient's actual
  // most-recent result in plain language, grounded in and citing the record.
  function explainResult() {
    const r = signals.latestResult;
    const q = r
      ? `Explain my most recent result — "${r.text}" (${r.ref}) — in simple, reassuring plain language. Say what it means for me and what to do next, and cite it.`
      : "Explain my most recent lab result in simple, reassuring plain language, and cite it.";
    void streamAgent(q);
  }
  // REAL: show the actual result's conclusion straight from the record (no agent).
  function viewResult() {
    const r = signals.latestResult;
    me("View my result");
    typing(() => {
      if (r) {
        push({ t: "card", data: { tone: r.critical ? "warn" : "good", kicker: "Lab result", title: r.text,
          text: r.conclusion ?? "This result is on file. Tap “Explain it simply” for a plain-language summary.",
          cite: `Grounded in your record · ${r.ref}`,
          actions: [{ kind: "pri", icon: <MessageSquareText className="h-4 w-4" />, label: "Explain it simply", act: () => explainResult() }] } });
      } else {
        push({ t: "ai", text: "You don't have any recent lab results on file right now." });
      }
      setQuicks(menu());
    }, 700);
  }

  // REAL: list the patient's actual active medications; each requests a real refill.
  function refill() {
    me("Refill a medicine");
    const meds = signals.medications;
    typing(() => {
      if (!meds.length) {
        push({ t: "ai", text: "You don't have any active medicines on record to refill right now." });
        setQuicks(menu());
        return;
      }
      push({ t: "ai", text: "Which one should I request a refill for?" });
      push({ t: "card", data: { tone: "info", kicker: "Your medicines", title: "Active prescriptions",
        facts: meds.map((m) => ({ x: m.text })),
        actions: meds.map((m, i) => ({ kind: i === 0 ? "pri" : "ghost", label: `Refill ${m.text}`, act: () => doRefill(m) } as Action)) } });
    });
  }
  function doRefill(m: { text: string; ref: string }) {
    me(`Refill ${m.text}`);
    void (async () => {
      setMsgs((mm) => [...mm, { t: "typing" }]);
      down();
      try {
        const res = await fetch("/api/portal/refill", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ medication: m.ref }) });
        setMsgs((mm) => mm.filter((n) => n.t !== "typing"));
        if (!res.ok) {
          push({ t: "ai", text: "Sorry — I couldn't send that refill request. Please try again." });
          setQuicks(menu());
          return;
        }
        push({ t: "card", data: { tone: "good", kicker: "Request sent", title: `${m.text} refill requested`,
          text: "Sent to your prescriber's team — they'll review and let you know when it's ready to collect.",
          cite: "Recorded in your record · pharmacy inbox",
          actions: [{ kind: "ghost", icon: <Bell className="h-4 w-4" />, label: "Notify me", act: () => typing(() => push({ t: "ai", text: "Will do — I'll let you know the moment it's ready. ✅" }), 600) }] } });
        setQuicks(menu());
      } catch {
        setMsgs((mm) => mm.filter((n) => n.t !== "typing"));
        push({ t: "ai", text: "Sorry — something went wrong sending that request." });
        setQuicks(menu());
      }
    })();
  }
  // REAL: fetch the patient's available slots from the scheduler, then book one.
  function book(reason: string, spec?: string) {
    me(`Book ${reason}`);
    setQuicks([]);
    void (async () => {
      setMsgs((m) => [...m, { t: "typing" }]);
      down();
      try {
        const qs = spec ? `?specialty=${encodeURIComponent(spec)}` : "";
        const res = await fetch(`/api/portal/booking${qs}`, { cache: "no-store" });
        const data = res.ok ? ((await res.json()) as { slots?: BSlot[] }) : { slots: [] };
        const slots = (data.slots ?? []).slice(0, 12);
        setMsgs((m) => m.filter((n) => n.t !== "typing"));
        if (!slots.length) {
          push({ t: "ai", text: spec ? `There are no open ${spec} slots right now — I can add you to the waitlist if you'd like.` : "There are no open appointment slots right now. Please try again later." });
          setQuicks(menu());
          return;
        }
        push({ t: "ai", text: "Here are the next available times — pick one 👇" });
        push({ t: "bslots", slots });
      } catch {
        setMsgs((m) => m.filter((n) => n.t !== "typing"));
        push({ t: "ai", text: "Sorry — I couldn't load available times just now." });
        setQuicks(menu());
      }
    })();
  }
  function confirmBooking(slot: BSlot) {
    me(`${dayLabel(slot.start)}, ${timeLabel(slot.start)}`);
    setQuicks([]);
    void (async () => {
      setMsgs((m) => [...m, { t: "typing" }]);
      down();
      try {
        const res = await fetch("/api/portal/booking", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ slot: slot.id }) });
        setMsgs((m) => m.filter((n) => n.t !== "typing"));
        if (!res.ok) {
          push({ t: "ai", text: res.status === 409 ? "Ah — that time was just taken. Pick another and I'll grab it." : "Sorry, I couldn't confirm that booking. Please try again." });
          if (res.status === 409) push({ t: "bslots", slots: [] });
          setQuicks(menu());
          return;
        }
        const b = (await res.json()) as BookResult;
        push({ t: "breceipt", b });
        window.setTimeout(() => {
          push({ t: "ai", text: "Booked ✨  Anything to add before you go?" });
          setQuicks([
            { label: "🎥 Join by video", act: () => startVideo() },
            { label: "📅 Add to calendar", act: () => note("Add to calendar", "Saved with a reminder the day before. 📅") },
            { label: "👨‍👩‍👧 Invite family", act: () => invite() },
            ...menu(),
          ]);
        }, 450);
      } catch {
        setMsgs((m) => m.filter((n) => n.t !== "typing"));
        push({ t: "ai", text: "Sorry — something went wrong confirming that." });
        setQuicks(menu());
      }
    })();
  }
  function note(s: string, r: string) { me(s); typing(() => push({ t: "ai", text: r }), 650); }
  // REAL: open a live Jitsi video room the clinician joins from the patient page.
  function startVideo() {
    me("Start my video visit");
    typing(() => { push({ t: "ai", text: "Connecting you to a secure video room — your clinician joins from their side. Tap Leave when you're done. 🎥" }); setInVideo(true); }, 500);
  }
  function invite() {
    me("Invite family");
    typing(() => { push({ t: "ai", text: "Who would you like to invite? They'll get a secure one-time link." });
      setQuicks([
        { label: "➕ My guardian", act: () => { me("My guardian"); typing(() => { push({ t: "card", data: { tone: "good", kicker: "Invitation sent", title: "Your guardian is invited", text: "They'll get a single-use link to join the video visit — no access to the rest of your record.", cite: "Family access · consent-based" } }); setQuicks(menu()); }, 800); } },
        { label: "Someone else", act: () => note("Someone else", "Share their number in the Care tab and I'll send the invite.") },
      ]); }, 700);
  }
  // REAL: the agent reads the record (immunisations, conditions, appointments)
  // to answer what the patient is due for.
  function dueCheck() {
    void streamAgent("Am I due for anything — vaccinations, screenings, or follow-ups? Check my record and tell me plainly, and cite it.");
  }
  // REAL: recent access rendered from the audit log (passed as a signal).
  function whoSaw() {
    me("Who saw my record?");
    typing(() => {
      const rows = signals.accessRecent.slice(0, 4);
      push({ t: "card", data: { tone: "info", kicker: "Transparency", title: "Recent access to your record",
        facts: rows.length
          ? rows.map((r) => ({ t: r.title.startsWith("You") ? "good" : undefined, x: `${r.title}${r.when ? ` — ${r.when}` : ""}` }))
          : [{ x: "No recent access recorded." }],
        text: "Every view is logged and tamper-proof. See the full list and revoke access in ‘Me’.",
        actions: [{ kind: "ghost", icon: <FileText className="h-4 w-4" />, label: "Open access log", act: () => window.dispatchEvent(new CustomEvent("mh:tab", { detail: "me" })) }] } });
      setQuicks(menu());
    }, 850);
  }

  // ---- greeting (proactive, driven by REAL record signals) ----
  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    const { overdueVaccines, latestResult } = signals;
    const actionable = overdueVaccines.length > 0 || !!latestResult;
    push({ t: "ai", text: tc(actionable ? "greetActionable" : "greetClear", { name: first }) });
    // NOTE: no cleanup clearing these timeouts — StrictMode's dev double-invoke
    // would fire it and the `ran` guard would then block re-scheduling, so the
    // cards would never appear. `ran` already makes this run exactly once.
    let delay = 600;
    if (overdueVaccines.length) {
      const d = delay; delay += 650;
      window.setTimeout(() => push({ t: "card", data: { tone: "urgent", kicker: "Action needed",
        title: overdueVaccines.length === 1 ? `${overdueVaccines[0]} is overdue` : `${overdueVaccines.length} immunisations are overdue`,
        text: overdueVaccines.join(", "), cite: "National immunisation schedule (EPI)",
        actions: [
          { kind: "pri", icon: <CalendarDays className="h-4 w-4" />, label: "Book vaccination", act: () => book("the overdue vaccination", "Child Health") },
          { kind: "ghost", icon: <Bell className="h-4 w-4" />, label: "Remind me", act: () => { me("Remind me tomorrow"); typing(() => push({ t: "ai", text: "Done — I'll nudge you tomorrow morning. 👍" }), 700); } },
        ] } }), d);
    }
    if (latestResult) {
      const d = delay; delay += 650;
      window.setTimeout(() => push({ t: "card", data: { tone: latestResult.critical ? "urgent" : "good", kicker: tc("resultReadyKicker"),
        title: latestResult.critical ? `${latestResult.text} ⚠️` : tc("resultReadyTitle"),
        text: `${latestResult.text}`,
        actions: [
          { kind: "pri", icon: <MessageSquareText className="h-4 w-4" />, label: tc("explainSimply"), act: () => explainResult() },
          { kind: "ghost", icon: <FileText className="h-4 w-4" />, label: tc("viewResult"), act: () => viewResult() },
        ] } }), d);
    }
    window.setTimeout(() => { push({ t: "ai", text: tc("orTap") }); push({ t: "services" }); setQuicks(menu()); }, delay + 200);
  }, [first, signals, push, me, typing, streamAgent, menu]);

  const services: { icon: React.ReactNode; c: string; t: string; d: string; act: () => void }[] = [
    { icon: <CalendarDays className="h-[18px] w-[18px]" />, c: "resp", t: tc("svcBook"), d: tc("svcBookSub"), act: () => book("a visit") },
    { icon: <Syringe className="h-[18px] w-[18px]" />, c: "activity", t: tc("svcVacc"), d: tc("svcVaccSub"), act: () => book("a vaccination", "Child Health") },
    { icon: <Sparkles className="h-[18px] w-[18px]" />, c: "nutri", t: tc("svcRefill"), d: signals.medsCount ? `${signals.medsCount} active` : tc("svcExplainAsk"), act: () => refill() },
    { icon: <FileText className="h-[18px] w-[18px]" />, c: "mind", t: tc("svcExplain"), d: signals.latestResult ? tc("svcExplainReady") : tc("svcExplainAsk"), act: () => (signals.latestResult ? explainResult() : void streamAgent("Summarise my recent results in plain language.")) },
  ];

  function renderCard(d: CardData) {
    return (
      <div className="mh-ccard">
        <div className="strip" style={{ background: TONE_COLOR[d.tone] }} />
        <div className="b">
          {d.kicker ? <span className="mh-k" style={{ background: TONE_BG[d.tone], color: TONE_COLOR[d.tone] }}>{d.kicker}</span> : null}
          <h4>{d.title}</h4>
          {d.text ? <p>{d.text}</p> : null}
          {d.facts ? (
            <div className="mh-facts">
              {d.facts.map((f, i) => (
                <div key={i} className="mh-fact"><span className="d" style={{ background: f.t ? FACT_COLOR[f.t] : "var(--mh-tint)" }} /><span>{f.x}</span></div>
              ))}
            </div>
          ) : null}
          {d.cite ? <div className="mh-cite">✓ {d.cite}</div> : null}
        </div>
        {d.actions ? (
          <div className="mh-acts">
            {d.actions.map((a, i) => (
              <button key={i} type="button" className={`mh-btn ${a.kind ?? "ghost"}`} onClick={a.act}>{a.icon}{a.label}</button>
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="mh flex h-[calc(100dvh-9rem)] flex-col overflow-hidden md:h-[calc(100dvh-5.5rem)]">
      {inVideo ? <VideoRoom room={videoRoom} displayName={name} onClose={() => setInVideo(false)} /> : null}
      <div ref={scrollRef} className="flex flex-1 flex-col gap-3 overflow-y-auto p-3.5">
        {msgs.map((n, i) => {
          if (n.t === "me") return <div key={i} className="mh-msg me"><div className="mh-bubble">{n.text}</div></div>;
          if (n.t === "typing") return <div key={i} className="mh-msg ai"><div className="mh-ai-row"><span className="mh-av"><Sparkles className="h-4 w-4" /></span><div className="mh-typing"><i /><i /><i /></div></div></div>;
          if (n.t === "ai")
            return (
              <div key={i} className="mh-msg ai">
                <div className="mh-ai-row">
                  <span className="mh-av"><Sparkles className="h-4 w-4" /></span>
                  <div className="min-w-0">
                    <div className="mh-bubble">{n.text ? <FormattedText text={n.text} /> : (n.streaming ? "…" : "")}</div>
                    {n.cites?.length ? (
                      <div className="mh-srcs">
                        <span className="mh-srcs-lbl">✓ Grounded in your record</span>
                        {n.cites.slice(0, 6).map((c, k) => (
                          <span key={k} className="mh-src">{c.resource_type ?? c.ref}</span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            );
          // node with an avatar + a rich body
          const body =
            n.t === "card" ? renderCard(n.data)
            : n.t === "services" ? (
                <div className="mh-carousel">
                  {services.map((s, k) => (
                    <button key={k} type="button" className="mh-svc" onClick={s.act}>
                      <span className="si" style={{ background: `var(--${s.c}-bg)`, color: `var(--${s.c})` }}>{s.icon}</span>
                      <div className="st">{s.t}</div><div className="sd">{s.d}</div>
                    </button>
                  ))}
                </div>
              )
            : n.t === "bslots" ? (
                <div>
                  {groupSlots(n.slots).map(([day, slots], k) => (
                    <div key={k}>
                      <div className="mh-daylab">{day}</div>
                      <div className="mh-slotgrid">
                        {slots.map((s) => (
                          <button key={s.id} type="button" className="mh-slotpill" onClick={() => confirmBooking(s)}>{timeLabel(s.start)}</button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )
            : n.t === "breceipt" ? (
                <div className="mh-ccard">
                  <div className="strip" style={{ background: "var(--activity)" }} />
                  <div className="b">
                    <svg className="mh-check" viewBox="0 0 52 52"><circle cx="26" cy="26" r="23" style={{ strokeDasharray: 150, strokeDashoffset: 150, animation: "mh-draw .5s .15s forwards" }} /><path d="M15 27l7 7 15-16" style={{ strokeDasharray: 44, strokeDashoffset: 44, animation: "mh-draw .4s .55s forwards" }} /></svg>
                    <h4 style={{ textAlign: "center", marginTop: 12 }}>Appointment confirmed</h4>
                    <div style={{ marginTop: 12 }}>
                      {n.b.specialty ? <div className="mh-rline"><span className="l">For</span><span className="v">{n.b.specialty}</span></div> : null}
                      <div className="mh-rline"><span className="l">When</span><span className="v">{dayLabel(n.b.start)}, {timeLabel(n.b.start)}</span></div>
                      <div className="mh-rline"><span className="l">Where</span><span className="v">Teaching Hospital</span></div>
                      <div className="mh-rline"><span className="l">Ref</span><span className="v" style={{ color: "var(--mh-tint-ink)" }}>{n.b.appointment_id ? `MA-${n.b.appointment_id}` : "—"}</span></div>
                    </div>
                  </div>
                </div>
              )
            : null;
          return <div key={i} className="mh-msg ai" style={{ maxWidth: "94%" }}><div className="mh-ai-row"><span className="mh-av"><Sparkles className="h-4 w-4" /></span><div style={{ flex: 1 }}>{body}</div></div></div>;
        })}
      </div>

      {quicks.length ? (
        <div className="mh-quick">
          {quicks.map((q, i) => (
            <button key={i} type="button" className="mh-chip" onClick={q.act}>{q.label}</button>
          ))}
        </div>
      ) : null}

      <form
        className="mh-composer"
        onSubmit={(e) => { e.preventDefault(); const v = input.trim(); if (!v) return; setInput(""); handleFree(v); }}
      >
        <button
          type="button"
          onClick={toggleVoice}
          aria-pressed={listening}
          aria-label={listening ? "Stop listening" : "Speak"}
          className="mh-circ mic"
          style={listening ? { background: "var(--heart)", color: "#fff", animation: "mh-pulse 1s ease-in-out infinite" } : undefined}
        >
          <Mic className="h-5 w-5" />
        </button>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder={tnav("ask")} aria-label={tnav("ask")} />
        <button type="submit" className="mh-circ send" disabled={busy || !input.trim()} aria-label="Send"><Send className="h-5 w-5" /></button>
      </form>
    </div>
  );
}
