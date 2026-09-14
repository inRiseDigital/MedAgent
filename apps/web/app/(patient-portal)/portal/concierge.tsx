"use client";
/*
 * Patient concierge (FR-3, 07 §6) — the chat-first home, matching the approved
 * premium prototype exactly: proactive nudge cards, a services shelf, and a
 * conversational-commerce booking flow (clinician carousel → slot picker →
 * animated receipt → upsells). Free-text and "Explain my result" stream the LIVE
 * agent over the BFF SSE (/api/chat); the guided flows are scripted UX. Styling
 * comes from the `.mh` premium theme.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Bell,
  CalendarDays,
  FileText,
  MessageSquareText,
  Mic,
  Paperclip,
  Send,
  Sparkles,
  Syringe,
} from "lucide-react";

import { VideoRoom } from "@/components/video-room";
import { streamAgentChat } from "@/lib/agent-stream";
import { Widget, type WidgetSpec } from "@/components/widgets";
import { Presence, type PresenceState } from "@/components/presence";
import { FormattedText } from "./formatted-text";
import { VoiceMode } from "./voice-mode";

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
  | { t: "ai"; text: string; streaming?: boolean; status?: string; cites?: { ref: string; resource_type?: string }[] }
  | { t: "me"; text: string }
  | { t: "image"; url: string; name?: string; pdf?: boolean }
  | { t: "typing" }
  | { t: "card"; data: CardData }
  | { t: "services" }
  | { t: "bslots"; slots: BSlot[] }
  | { t: "breceipt"; b: BookResult }
  | { t: "widget"; spec: WidgetSpec };
type Quick = { label: string; act: () => void };
type BSlot = { id: string; start?: string; end?: string; specialty?: string; facility?: string };
type BookResult = { appointment_id?: string; start?: string; end?: string; specialty?: string; facility?: string };

// `info` uses the AA-safe deep teal (--mh-tint-ink) so the kicker label holds
// contrast on the light-teal tint; the others already pair colour + tint at AA.
const TONE_COLOR: Record<Tone, string> = { urgent: "var(--heart)", good: "var(--activity)", warn: "var(--nutri)", info: "var(--mh-tint-ink)" };
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
  // Stable conversation id (H0-S1): the server owns the thread keyed by this, so the
  // conversation survives a reload. Persisted per patient in localStorage.
  const convId = useMemo(() => {
    try {
      const k = `mh:conv:${patientPhn}`;
      let v = localStorage.getItem(k);
      if (!v) { v = crypto.randomUUID?.() ?? `c-${Date.now()}-${Math.random().toString(36).slice(2)}`; localStorage.setItem(k, v); }
      return v;
    } catch { return `conv-${patientPhn}`; }
  }, [patientPhn]);
  const tnav = useTranslations("patientNav");
  const tc = useTranslations("concierge");
  const [msgs, setMsgs] = useState<Node[]>([]);
  const [quicks, setQuicks] = useState<Quick[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [inVideo, setInVideo] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  // The Presence orb's live state, driven by real agent activity (below).
  const [presence, setPresence] = useState<PresenceState>("idle");
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  // The confirm-action card awaiting a decision — so voice can act on "yes, book it".
  const pendingConfirm = useRef<{ action: string; params: Record<string, unknown> } | null>(null);
  const ran = useRef(false);
  const videoRoom = `medagent-${patientPhn}`; // deterministic: doctor + patient meet here

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
    async (question: string, opts?: { proactive?: boolean }) => {
      if (busy) return "";
      setBusy(true);
      setPresence("thinking");
      const proactive = opts?.proactive === true;
      const prior = msgs.filter((n): n is Extract<Node, { t: "ai" | "me" }> => n.t === "ai" || n.t === "me");
      const history = proactive ? prior : [...prior, { t: "me" as const, text: question }];
      setMsgs((m) => proactive
        ? [...m, { t: "ai", text: "", streaming: true }]
        : [...m, { t: "me", text: question }, { t: "ai", text: "", streaming: true }]);
      down();
      // Target THIS turn's AI node by finding the last "ai" node — not "the last
      // message" — because data-cards push card nodes after it. Otherwise the
      // streaming indicator ("…") never clears and a no-text turn stays blank.
      const lastAiIndex = (list: Node[]): number => {
        for (let i = list.length - 1; i >= 0; i--) if (list[i]!.t === "ai") return i;
        return -1;
      };
      const bump = (fn: (t: Node & { t: "ai" }) => Node) =>
        setMsgs((m) => {
          const idx = lastAiIndex(m);
          return idx < 0 ? m : m.map((n, i) => (i === idx && n.t === "ai" ? fn(n) : n));
        });
      let full = "";
      // Client-side safety timeout: the server bounds a run (~90s), but a stalled
      // network shouldn't leave the "…" indicator spinning forever.
      const ctrl = new AbortController();
      const timer = window.setTimeout(() => ctrl.abort(), 120_000);
      try {
        const result = await streamAgentChat(
          {
            patient_id: patientPhn,
            audience: "patient",
            locale,
            conversation_id: convId,
            mode: proactive ? "proactive" : "chat",
            messages: proactive
              ? [{ role: "user", content: "(open)" }]
              : history.map((t) => ({ role: t.t === "me" ? "user" : "assistant", content: t.text })),
          },
          {
            signal: ctrl.signal,
            onEvent: (o) => {
              if (o.type === "text-delta" && o.delta) { setPresence("speaking"); full += o.delta; bump((n) => ({ ...n, text: n.text + o.delta, status: undefined })); down(); }
              else if (o.type === "data-status" && typeof o.text === "string") { bump((n) => ({ ...n, status: o.text })); down(); }
              else if (o.type === "data-citations" && Array.isArray(o.data)) { const cites = o.data as { ref: string; resource_type?: string }[]; bump((n) => ({ ...n, cites })); down(); }
              else if (o.type === "data-cards" && Array.isArray(o.data)) {
                for (const c of o.data as { tone?: Tone; title?: string; points?: string[] }[]) {
                  if (!c.title) continue;
                  push({ t: "card", data: { tone: c.tone ?? "info", kicker: "Summary", title: c.title, facts: (c.points ?? []).map((x) => ({ x })) } });
                }
              }
              else if (o.type === "data-widget" && o.widget) {
                const spec = o.widget as WidgetSpec;
                // A safety/escalation widget makes the Presence FLARE — a brief, deliberate
                // attention-grab (~2.6s), then it settles; the red widget card remains the
                // persistent signal, so the orb never sits permanently red (alarm fatigue).
                if (spec.kind === "safety-alert" || spec.kind === "escalation") {
                  setPresence("alert");
                  window.setTimeout(() => setPresence((p) => (p === "alert" ? "idle" : p)), 2600);
                }
                // Remember a confirm card so voice ("yes, book it") can act on it.
                if (spec.kind === "confirm-action") {
                  pendingConfirm.current = { action: String(spec.data.action ?? ""), params: (spec.data.params as Record<string, unknown>) ?? {} };
                }
                push({ t: "widget", spec }); down();
              }
            },
          },
        );
        if (!result.ok) {
          bump((n) => ({ ...n, text: "Sorry — the assistant is unavailable right now.", streaming: false }));
          return full;
        }
      } catch {
        bump((n) => ({ ...n, text: "Sorry — something went wrong. Please try again.", streaming: false }));
      } finally {
        window.clearTimeout(timer);
        setBusy(false);
        setPresence("idle");
        // Always settle THIS turn's AI node: clear the "…" indicator, and if the
        // stream produced no text at all (should not happen — the server floors an
        // answer — but never leave a silent blank bubble), show a retry line.
        setMsgs((m) => {
          const idx = lastAiIndex(m);
          if (idx < 0) return m;
          return m.map((n, i) => {
            if (i !== idx || n.t !== "ai") return n;
            return { ...n, streaming: false, text: n.text || "Sorry — I couldn't answer that just now. Please try again." };
          });
        });
        down();
      }
      return full;
    },
    [busy, msgs, patientPhn, down, locale, convId],
  );

  // ---- multimodal (P4b): share a photo (lab report, medicine box, symptom) and
  // the agent reads it on a vision model, streaming a plain-language explanation.
  const sendImage = useCallback(
    async (file: File) => {
      if (busy) return;
      const isPdf = file.type === "application/pdf";
      if (!file.type.startsWith("image/") && !isPdf) return;
      if (file.size > 6_000_000) {
        push({ t: "ai", text: "That file is a bit large — please share one under 6 MB. 🙏" });
        return;
      }
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(String(r.result));
        r.onerror = () => reject(new Error("read failed"));
        r.readAsDataURL(file);
      }).catch(() => "");
      if (!dataUrl) return;
      const base64 = dataUrl.split(",")[1] ?? "";
      setBusy(true);
      push({ t: "image", url: dataUrl, name: file.name, pdf: isPdf });
      setMsgs((m) => [...m, { t: "ai", text: "", streaming: true }]);
      down();
      const bump = (fn: (t: Node & { t: "ai" }) => Node) =>
        setMsgs((m) => {
          for (let i = m.length - 1; i >= 0; i--) if (m[i]!.t === "ai") return m.map((n, k) => (k === i && n.t === "ai" ? fn(n) : n));
          return m;
        });
      let got = "";
      const ctrl = new AbortController();
      const timer = window.setTimeout(() => ctrl.abort(), 120_000);
      try {
        const result = await streamAgentChat(
          { image_base64: base64, mime: file.type, question: "" },
          {
            endpoint: "/api/portal/vision",
            signal: ctrl.signal,
            onEvent: (o) => {
              if (o.type === "text-delta" && o.delta) { got += o.delta; bump((n) => ({ ...n, text: n.text + o.delta })); down(); }
              // S9: extracted report values arrive as a stat-grid widget.
              else if (o.type === "data-widget" && o.widget) { push({ t: "widget", spec: o.widget as WidgetSpec }); down(); }
            },
          },
        );
        if (!result.ok) bump((n) => ({ ...n, text: "Sorry — I couldn't read that image just now.", streaming: false }));
      } catch {
        bump((n) => ({ ...n, text: "Sorry — something went wrong reading that image.", streaming: false }));
      } finally {
        window.clearTimeout(timer);
        setBusy(false);
        bump((n) => ({ ...n, streaming: false, text: n.text || "Sorry — I couldn't read that image. Please try another photo." }));
        void got;
        down();
      }
    },
    [busy, push, down],
  );

  // ---- scripted conversational-commerce flows ----
  const menu = useCallback((): Quick[] => [
    { label: tc("chipRefill"), act: () => refill() },
    { label: tc("chipBook"), act: () => book("a follow-up") },
    { label: tc("chipDue"), act: () => dueCheck() },
    { label: tc("chipVideo"), act: () => startVideo() },
    { label: tc("chipWho"), act: () => whoSaw() },
    { label: "🔒 Privacy & consent", act: () => consent() },
  ], []); // eslint-disable-line react-hooks/exhaustive-deps

  // Agent-first: every typed question goes to the LIVE patient-persona agent,
  // which reads the real FHIR record and answers with citations. Scripted flows
  // fire only from explicit card/chip taps (booking, refill, the greeting cards).
  function handleFree(text: string) {
    void streamAgent(text);
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
      const rows = signals.accessRecent.slice(0, 6);
      // Render the real audit trail as the access-log transparency widget (H0/S2).
      push({ t: "ai", text: rows.length
        ? "Here's who has looked at your record recently. Every view is logged and tamper-proof. 🛡️"
        : "No one has accessed your record recently — and every view is always logged. 🛡️" });
      if (rows.length) {
        push({ t: "widget", spec: {
          id: "w_access", kind: "access-log", title: "Who has seen your record",
          data: { items: rows.map((r) => ({
            who: r.title.replace(/^You\b/, "You"),
            when: r.when ?? "",
            you: r.title.startsWith("You"),
          })) },
        } });
      }
      setQuicks(menu());
    }, 700);
  }

  // ---- consent (H0/S2): view & change who can access the record, end-to-end via
  // the gated /api/portal/consent route. One real scope today (face recognition);
  // the panel grows as the backend exposes more.
  const CONSENT_LABELS: Record<string, { label: string; detail: string }> = {
    face_recognition: { label: "Face recognition at check-in", detail: "Lets check-in kiosks verify you by your face." },
  };
  async function fetchConsent(): Promise<Record<string, boolean>> {
    try { const r = await fetch("/api/portal/consent", { cache: "no-store" }); return r.ok ? await r.json() : {}; }
    catch { return {}; }
  }
  function pushConsentPanel(state: Record<string, boolean>) {
    const scopes = Object.keys(CONSENT_LABELS).map((k) => ({
      id: `consent:${k}`, label: CONSENT_LABELS[k]!.label, detail: CONSENT_LABELS[k]!.detail, granted: !!state[k],
    }));
    push({ t: "widget", spec: { id: "w_consent", kind: "consent-panel", title: "Who can access your record", data: { scopes } } });
  }
  function consent() {
    me("Privacy & consent");
    void (async () => {
      const state = await fetchConsent();
      push({ t: "ai", text: "Here's what you've allowed. Tap a switch to change it — every view of your record is always logged. 🔒" });
      pushConsentPanel(state);
      setQuicks(menu());
    })();
  }
  async function toggleConsent(key: string) {
    const cur = await fetchConsent();
    const next = !cur[key];
    try {
      const r = await fetch("/api/portal/consent", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...cur, [key]: next }) });
      if (r.ok) { pushConsentPanel((await r.json()) as Record<string, boolean>); push({ t: "ai", text: `Updated — ${CONSENT_LABELS[key]?.label ?? key} is now ${next ? "on" : "off"}. ✅` }); }
      else push({ t: "ai", text: "Sorry — I couldn't update that just now." });
    } catch { push({ t: "ai", text: "Sorry — something went wrong updating that." }); }
  }

  // Execute a proposed confirm-action (refill/book/video) — shared by the card's
  // Confirm button AND voice ("yes, book it"). The model proposes; this commits
  // via the gated flows (P3 invariant). Returns whether it succeeded.
  async function runConfirm(action: string, params: Record<string, unknown>): Promise<boolean> {
    pendingConfirm.current = null;
    try {
      if (action === "refill") {
        const res = await fetch("/api/portal/refill", {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ medication: params.medication }),
        });
        if (!res.ok) return false;
        const d = (await res.json().catch(() => ({}))) as { medication?: string };
        const med = d.medication ?? String(params.medication ?? "your medicine");
        push({ t: "widget", spec: { id: `order-${Date.now()}`, kind: "order-status", title: "Refill request", data: {
          label: med,
          steps: [
            { key: "requested", label: "Requested", state: "active" },
            { key: "review", label: "Pharmacy review", state: "pending" },
            { key: "ready", label: "Ready to collect", state: "pending" },
          ],
        } } });
        return true;
      }
      if (action === "book") {
        book(typeof params.reason === "string" && params.reason ? params.reason : "a visit");
        return true;
      }
      if (action === "video") {
        startVideo();
        return true;
      }
    } catch { /* fall through */ }
    return false;
  }

  // Voice turn: if a confirm card is pending and the patient says "yes/confirm/go
  // ahead", execute it hands-free; otherwise route the utterance to the agent.
  async function voiceAsk(text: string): Promise<string> {
    const p = pendingConfirm.current;
    if (p && /\b(yes|yeah|yep|confirm|go ahead|do it|please do|okay|ok|sure|book it|send it)\b/i.test(text)) {
      const ok = await runConfirm(p.action, p.params);
      return ok ? "Done — I've taken care of that for you. ✅" : "Sorry, I couldn't complete that just now.";
    }
    return streamAgent(text);
  }

  // ---- greeting (proactive, driven by REAL record signals) ----
  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    // P5 — the agent AUTHORS a grounded proactive greeting: it streams a warm,
    // cited opening (name + the most important thing right now) and renders the
    // safety-alert / record-links / next-best-action widgets, replacing the old
    // static scripted nudges. The services shelf + quick chips follow.
    void streamAgent("", { proactive: true }).finally(() => {
      push({ t: "services" });
      setQuicks(menu());
    });
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
      {voiceOpen ? <VoiceMode locale={locale} name={name} ask={voiceAsk} onClose={() => setVoiceOpen(false)} /> : null}
      <div ref={scrollRef} className="flex flex-1 flex-col gap-3 overflow-y-auto p-3.5">
        {msgs.map((n, i) => {
          if (n.t === "me") return <div key={i} className="mh-msg me"><div className="mh-bubble">{n.text}</div></div>;
          if (n.t === "image")
            return (
              <div key={i} className="mh-msg me">
                {n.pdf ? (
                  <div className="flex items-center gap-2.5 rounded-2xl px-3.5 py-3 text-[13px] font-semibold"
                    style={{ background: "var(--primary)", color: "var(--primary-foreground)", boxShadow: "var(--mh-shadow)" }}>
                    <FileText className="h-5 w-5" />
                    <span className="max-w-[220px] truncate">{n.name ?? "Document.pdf"}</span>
                  </div>
                ) : (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img src={n.url} alt="Shared photo" className="max-h-56 rounded-2xl object-cover" style={{ boxShadow: "var(--mh-shadow)" }} />
                )}
              </div>
            );
          if (n.t === "typing") return <div key={i} className="mh-msg ai"><div className="mh-ai-row"><span className="mh-av"><Sparkles className="h-4 w-4" /></span><div className="mh-typing"><i /><i /><i /></div></div></div>;
          if (n.t === "ai")
            return (
              <div key={i} className="mh-msg ai">
                <div className="mh-ai-row">
                  <span className="mh-av"><Sparkles className="h-4 w-4" /></span>
                  <div className="min-w-0">
                    {!n.text && n.streaming && n.status ? (
                      <div className="mh-think" aria-live="polite"><Sparkles className="h-3.5 w-3.5" /><span>{n.status}</span><i /><i /><i /></div>
                    ) : (
                      <div className="mh-bubble">{n.text ? <FormattedText text={n.text} /> : (n.streaming ? "…" : "")}</div>
                    )}
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
            : n.t === "widget" ? (
                <Widget
                  spec={n.spec}
                  onAction={(id) => {
                    if (id.startsWith("consent:")) { void toggleConsent(id.slice("consent:".length)); return; }
                    void streamAgent(id.includes("/") ? `Tell me about this record item (${id}).` : id);
                  }}
                  onConfirm={runConfirm}
                />
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
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif,application/pdf"
          className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void sendImage(f); e.target.value = ""; }}
        />
        <span aria-hidden="true" style={{ flex: "none", width: 40, height: 40, display: "grid", placeItems: "center" }}>
          <Presence state={presence} size={40} />
        </span>
        <button type="button" onClick={() => fileRef.current?.click()} disabled={busy} aria-label="Share a photo" className="mh-circ mic">
          <Paperclip className="h-5 w-5" />
        </button>
        <button type="button" onClick={() => setVoiceOpen(true)} aria-label="Voice mode" className="mh-circ mic">
          <Mic className="h-5 w-5" />
        </button>
        <input value={input} onChange={(e) => setInput(e.target.value)} onFocus={() => { if (!busy) setPresence("listening"); }} onBlur={() => { if (!busy) setPresence("idle"); }} placeholder={tnav("ask")} aria-label={tnav("ask")} />
        <button type="submit" className="mh-circ send" disabled={busy || !input.trim()} aria-label="Send"><Send className="h-5 w-5" /></button>
      </form>
    </div>
  );
}
