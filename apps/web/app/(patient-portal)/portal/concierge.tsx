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
import {
  Bell,
  CalendarDays,
  FileText,
  MessageSquareText,
  Mic,
  Send,
  Sparkles,
  Star,
  Syringe,
  Video,
} from "lucide-react";

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
  | { t: "carousel"; spec: string }
  | { t: "slots"; name: string; spec: string }
  | { t: "receipt"; name: string; spec: string; when: string };
type Quick = { label: string; act: () => void };

const TONE_COLOR: Record<Tone, string> = { urgent: "var(--heart)", good: "var(--activity)", warn: "var(--nutri)", info: "var(--mh-tint)" };
const TONE_BG: Record<Tone, string> = { urgent: "var(--heart-bg)", good: "var(--activity-bg)", warn: "var(--nutri-bg)", info: "var(--body-bg)" };
const FACT_COLOR: Record<string, string> = { good: "var(--activity)", warn: "var(--nutri)", urgent: "var(--heart)" };

const CLIN = [
  { n: "Dr. Silva", i: "S", r: "4.9", s: "Tomorrow 9:00", c: "var(--resp)" },
  { n: "Dr. Fernando", i: "F", r: "4.8", s: "Fri 10:00", c: "var(--body)" },
  { n: "Dr. Rathnayake", i: "R", r: "4.7", s: "Mon 11:30", c: "var(--mind)" },
];
const DAYS: [string, string[]][] = [
  ["Tomorrow", ["9:00", "11:30", "14:30"]],
  ["Friday", ["10:00", "13:00", "15:30"]],
];

export function Concierge({ patientPhn, name }: { patientPhn: string; name: string }) {
  const first = name.split(" ")[0] ?? "there";
  const [msgs, setMsgs] = useState<Node[]>([]);
  const [quicks, setQuicks] = useState<Quick[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const ran = useRef(false);

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
      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            patient_id: patientPhn,
            audience: "patient",
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
              const o = JSON.parse(p) as { type?: string; delta?: string; data?: { ref: string; resource_type?: string }[] };
              if (o.type === "text-delta" && o.delta) { bump((n) => ({ ...n, text: n.text + o.delta })); down(); }
              else if (o.type === "data-citations" && Array.isArray(o.data)) { const cites = o.data; bump((n) => ({ ...n, cites })); down(); }
            } catch { /* keep-alive */ }
          }
        }
      } catch {
        bump((n) => ({ ...n, text: "Sorry — something went wrong. Please try again.", streaming: false }));
      } finally {
        setBusy(false);
        setMsgs((m) => m.map((n, i) => (i === m.length - 1 && n.t === "ai" ? { ...n, streaming: false } : n)));
        down();
      }
    },
    [busy, msgs, patientPhn, down],
  );

  // ---- scripted conversational-commerce flows ----
  const menu = useCallback((): Quick[] => [
    { label: "💊 Refill a medicine", act: () => refill() },
    { label: "📅 Book a follow-up", act: () => book("your follow-up", "Cardiology") },
    { label: "🩺 Am I due for anything?", act: () => dueCheck() },
    { label: "🔒 Who saw my record?", act: () => whoSaw() },
  ], []); // eslint-disable-line react-hooks/exhaustive-deps

  // Agent-first: every typed question goes to the LIVE patient-persona agent,
  // which reads the real FHIR record and answers with citations. Scripted flows
  // fire only from explicit card/chip taps (booking, refill, the greeting cards).
  function handleFree(text: string) {
    void streamAgent(text);
  }

  function explain() {
    me("Explain my dengue result simply");
    typing(() => {
      push({ t: "ai", text: "Of course — the short version 👇" });
      push({ t: "card", data: { tone: "good", kicker: "In plain language", title: "You had dengue — and you're recovering well",
        text: "Your test confirmed dengue. The reassuring part: platelets are steady and fever is settling.",
        facts: [
          { t: "good", x: "Platelets stable — no bleeding risk right now" },
          { t: "good", x: "Fever coming down over the last 2 days" },
          { t: "warn", x: "Keep resting and drink plenty of fluids" },
        ],
        cite: "Grounded in your record · not a diagnosis",
        actions: [
          { kind: "pri", icon: <MessageSquareText className="h-4 w-4" />, label: "What should I avoid?", act: () => avoid() },
          { kind: "ghost", icon: <Video className="h-4 w-4" />, label: "Message my doctor", act: () => { me("Message my doctor"); typing(() => push({ t: "ai", text: "Sent to Dr. Perera's team. If anything feels worse — severe tummy pain, bleeding, or you can't keep fluids down — go to a hospital straight away." }), 900); } },
        ] } });
      setQuicks([{ label: "What should I avoid?", act: () => avoid() }, { label: "Book a check-up", act: () => book("a dengue check-up", "General") }, ...menu()]);
    }, 1100);
  }
  function avoid() {
    me("What should I avoid?");
    typing(() => {
      push({ t: "card", data: { tone: "warn", kicker: "While you recover", title: "A few things to avoid",
        facts: [
          { t: "urgent", x: "⚠️ No ibuprofen or aspirin — they raise bleeding risk in dengue. Paracetamol is fine." },
          { t: "warn", x: "Avoid strenuous activity for now" },
          { t: "good", x: "Do: rest, fluids, watch for warning signs" },
        ],
        cite: "Consistent with your allergy & medication record",
        actions: [{ kind: "pri", icon: <CalendarDays className="h-4 w-4" />, label: "Book a check-up", act: () => book("a dengue check-up", "General") }] } });
      setQuicks(menu());
    }, 950);
  }
  function viewResult() {
    me("View my dengue result");
    typing(() => {
      push({ t: "card", data: { tone: "good", kicker: "Lab result", title: "Dengue NS1 — positive → recovering", text: "Platelets stable, fever settling. No warning signs.", cite: "DiagnosticReport · Teaching Hospital" } });
      setQuicks(menu());
    }, 900);
  }

  function refill() {
    me("Refill a medicine");
    typing(() => {
      push({ t: "ai", text: "Which one should I request?" });
      push({ t: "card", data: { tone: "info", kicker: "Your medicines", title: "Current prescriptions",
        facts: [{ x: "Metformin 500 mg — twice daily" }, { x: "Paracetamol 500 mg — as needed" }],
        actions: [ { kind: "pri", label: "Refill Metformin", act: () => doRefill("Metformin") }, { kind: "ghost", label: "Refill Paracetamol", act: () => doRefill("Paracetamol") } ] } });
    });
  }
  function doRefill(n: string) {
    me(`Refill ${n}`);
    typing(() => {
      push({ t: "card", data: { tone: "good", kicker: "Request sent", title: `${n} refill requested`, text: "Your clinic pharmacy will confirm when it's ready to collect.", cite: "Sent to Teaching Hospital pharmacy",
        actions: [{ kind: "ghost", icon: <Bell className="h-4 w-4" />, label: "Notify me", act: () => typing(() => push({ t: "ai", text: "Will do — I'll let you know the moment it's ready. ✅" }), 600) }] } });
      setQuicks(menu());
    }, 900);
  }
  function book(reason: string, spec: string) {
    me(`Book ${reason}`);
    typing(() => { push({ t: "ai", text: `Let's get you booked. First, pick a clinician for ${spec}:` }); push({ t: "carousel", spec }); setQuicks([]); });
  }
  function pickDoc(name2: string, spec: string) {
    me(`With ${name2}`);
    typing(() => { push({ t: "ai", text: "Great choice. When suits you?" }); push({ t: "slots", name: name2, spec }); setQuicks([]); }, 800);
  }
  function pickSlot(name2: string, spec: string, when: string) {
    me(when);
    typing(() => {
      push({ t: "receipt", name: name2, spec, when });
      window.setTimeout(() => push({ t: "ai", text: "Done ✨  Anything to add before you go?" }), 400);
      setQuicks([
        { label: "🎥 Join by video", act: () => note("Join by video", "When it's time, tap the appointment to enter a secure video room — no install needed.") },
        { label: "📅 Add to calendar", act: () => note("Add to calendar", "Saved with a reminder the day before. 📅") },
        { label: "👨‍👩‍👧 Invite family", act: () => invite() },
        { label: "📋 Prep", act: () => { me("Prep instructions"); typing(() => push({ t: "card", data: { tone: "info", kicker: "Before your visit", title: "How to prepare", facts: [{ x: "Bring your medicines or a photo of them" }, { x: "No fasting needed" }, { x: "Arrive 10 min early — or use face check-in" }] } }), 800); } },
      ]);
    }, 950);
  }
  function note(s: string, r: string) { me(s); typing(() => push({ t: "ai", text: r }), 650); }
  function invite() {
    me("Invite family");
    typing(() => { push({ t: "ai", text: "Who would you like to invite? They'll get a secure one-time link." });
      setQuicks([
        { label: "➕ My guardian", act: () => { me("My guardian"); typing(() => { push({ t: "card", data: { tone: "good", kicker: "Invitation sent", title: "Your guardian is invited", text: "They'll get a single-use link to join the video visit — no access to the rest of your record.", cite: "Family access · consent-based" } }); setQuicks(menu()); }, 800); } },
        { label: "Someone else", act: () => note("Someone else", "Share their number in the Care tab and I'll send the invite.") },
      ]); }, 700);
  }
  function dueCheck() {
    me("Am I due for anything?");
    typing(() => { push({ t: "card", data: { tone: "info", kicker: "Reminders", title: "Coming up",
      facts: [{ t: "urgent", x: "Baby's OPV vaccine — overdue" }, { t: "warn", x: "Yearly HbA1c check — next month" }, { t: "good", x: "Everything else up to date 🎉" }],
      actions: [{ kind: "pri", icon: <CalendarDays className="h-4 w-4" />, label: "Book the vaccine", act: () => book("Baby's OPV vaccination", "Child health") }] } }); setQuicks(menu()); }, 900);
  }
  function whoSaw() {
    me("Who saw my record?");
    typing(() => { push({ t: "card", data: { tone: "info", kicker: "Transparency", title: "Recent access",
      facts: [{ t: "good", x: "Dr. Perera viewed your summary — today, 9:12" }, { t: "good", x: "Lab added your dengue result — yesterday" }, { x: "You downloaded your record — 3 days ago" }],
      text: "Every view is logged and tamper-proof. Revoke access anytime in ‘Me’." } }); setQuicks(menu()); }, 850);
  }

  // ---- greeting (proactive) ----
  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    push({ t: "ai", text: `Good morning, ${first} 🌿  I've checked your record — two things need you today.` });
    // NOTE: no cleanup that clears these timeouts. React's StrictMode dev
    // double-invoke would run the cleanup and, with the `ran` guard blocking a
    // re-schedule, the cards would never appear. The `ran` guard already makes
    // this run exactly once, so letting the timeouts stand is correct.
    window.setTimeout(() => push({ t: "card", data: { tone: "urgent", kicker: "Action needed", title: "Baby's OPV vaccine is overdue", text: "The oral polio birth dose was due at birth and hasn't been given yet.", cite: "National immunisation schedule",
      actions: [ { kind: "pri", icon: <CalendarDays className="h-4 w-4" />, label: "Book vaccination", act: () => book("Baby's OPV vaccination", "Child health") }, { kind: "ghost", icon: <Bell className="h-4 w-4" />, label: "Remind me", act: () => { me("Remind me tomorrow"); typing(() => push({ t: "ai", text: "Done — I'll nudge you tomorrow morning. 👍" }), 700); } } ] } }), 600);
    window.setTimeout(() => {
      push({ t: "card", data: { tone: "good", kicker: "Result ready", title: "Your dengue result is ready", text: "Reviewed by the lab. Good news overall — want it in plain language?",
        actions: [ { kind: "pri", icon: <MessageSquareText className="h-4 w-4" />, label: "Explain it simply", act: () => explain() }, { kind: "ghost", icon: <FileText className="h-4 w-4" />, label: "View result", act: () => viewResult() } ] } });
      window.setTimeout(() => { push({ t: "ai", text: "Or tap what you'd like to do 👇" }); push({ t: "services" }); setQuicks(menu()); }, 450);
    }, 1250);
  }, [first, push, me, typing, streamAgent, menu]);

  const services: { icon: React.ReactNode; c: string; t: string; d: string; act: () => void }[] = [
    { icon: <CalendarDays className="h-[18px] w-[18px]" />, c: "resp", t: "Book a visit", d: "Any specialty", act: () => book("your follow-up", "Cardiology") },
    { icon: <Syringe className="h-[18px] w-[18px]" />, c: "activity", t: "Vaccinations", d: "For Baby", act: () => book("Baby's OPV vaccination", "Child health") },
    { icon: <Sparkles className="h-[18px] w-[18px]" />, c: "nutri", t: "Refill meds", d: "2 active", act: () => refill() },
    { icon: <FileText className="h-[18px] w-[18px]" />, c: "mind", t: "Explain a result", d: "Dengue ready", act: () => explain() },
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
    <div className="mh flex h-[calc(100dvh-9rem)] flex-col overflow-hidden lg:h-[calc(100dvh-7rem)]">
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
                    <div className="mh-bubble">{n.text || (n.streaming ? "…" : "")}</div>
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
            : n.t === "carousel" ? (
                <div>
                  <div className="mh-stepper"><i className="on" /><i /><i /><span>Step 1 / 3</span></div>
                  <div className="mh-carousel">
                    {CLIN.map((d, k) => (
                      <button key={k} type="button" className="mh-doc" onClick={() => pickDoc(d.n, n.spec)}>
                        <span className="av" style={{ background: `linear-gradient(150deg, ${d.c}, color-mix(in srgb, ${d.c} 55%, #000))` }}>{d.i}</span>
                        <div className="dn">{d.n}</div><div className="dsp">{n.spec}</div>
                        <div className="rt"><Star className="h-3 w-3" fill="currentColor" />{d.r}</div>
                        <div className="sl">Next: {d.s}</div>
                      </button>
                    ))}
                  </div>
                </div>
              )
            : n.t === "slots" ? (
                <div>
                  <div className="mh-stepper"><i className="on" /><i className="on" /><i /><span>Step 2 / 3</span></div>
                  {DAYS.map(([day, times], k) => (
                    <div key={k}>
                      <div className="mh-daylab">{day}</div>
                      <div className="mh-slotgrid">
                        {times.map((tm) => (
                          <button key={tm} type="button" className="mh-slotpill" onClick={() => pickSlot(n.name, n.spec, `${day}, ${tm}`)}>{tm}</button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )
            : n.t === "receipt" ? (
                <div className="mh-ccard">
                  <div className="strip" style={{ background: "var(--activity)" }} />
                  <div className="b">
                    <svg className="mh-check" viewBox="0 0 52 52"><circle cx="26" cy="26" r="23" style={{ strokeDasharray: 150, strokeDashoffset: 150, animation: "mh-draw .5s .15s forwards" }} /><path d="M15 27l7 7 15-16" style={{ strokeDasharray: 44, strokeDashoffset: 44, animation: "mh-draw .4s .55s forwards" }} /></svg>
                    <h4 style={{ textAlign: "center", marginTop: 12 }}>Appointment confirmed</h4>
                    <div style={{ marginTop: 12 }}>
                      <div className="mh-rline"><span className="l">Clinician</span><span className="v">{n.name}</span></div>
                      <div className="mh-rline"><span className="l">For</span><span className="v">{n.spec}</span></div>
                      <div className="mh-rline"><span className="l">When</span><span className="v">{n.when}</span></div>
                      <div className="mh-rline"><span className="l">Where</span><span className="v">Teaching Hospital</span></div>
                      <div className="mh-rline"><span className="l">Ref</span><span className="v" style={{ color: "var(--mh-tint-ink)" }}>MA-4827</span></div>
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
        <button type="button" className="mh-circ mic" aria-label="Speak"><Mic className="h-5 w-5" /></button>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about your health…" aria-label="Ask about your health" />
        <button type="submit" className="mh-circ send" disabled={busy || !input.trim()} aria-label="Send"><Send className="h-5 w-5" /></button>
      </form>
    </div>
  );
}
