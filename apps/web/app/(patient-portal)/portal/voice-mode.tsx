"use client";
/*
 * Immersive voice mode (ChatGPT-style): a full-screen overlay with an animated
 * orb that reacts to the mic, for a hands-free spoken conversation. It runs its
 * own speech recognition + amplitude meter (Web Audio) + speech synthesis, and
 * routes each utterance through `ask` (the concierge's live agent) so the spoken
 * turns also appear in the chat log behind it. Free — browser Web Speech API.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Mic, X } from "lucide-react";

type Status = "listening" | "thinking" | "speaking" | "idle" | "unsupported";

type Recognition = {
  lang: string; interimResults: boolean; continuous: boolean; maxAlternatives: number;
  start: () => void; stop: () => void; abort: () => void;
  onresult: ((e: { resultIndex: number; results: { length: number; [i: number]: { isFinal: boolean; 0: { transcript: string } } } }) => void) | null;
  onend: (() => void) | null; onerror: (() => void) | null;
};

const STATUS_LABEL: Record<Status, string> = {
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Speaking…",
  idle: "Tap the orb to talk",
  unsupported: "Voice isn't supported in this browser",
};

export function VoiceMode({ locale, name, ask, onClose }: {
  locale: string;
  name: string;
  ask: (text: string) => Promise<string>;
  onClose: () => void;
}) {
  const bcp47 = locale === "si" ? "si-LK" : locale === "ta" ? "ta-LK" : "en-US";
  const [status, setStatus] = useState<Status>("idle");
  const [caption, setCaption] = useState("");
  const [level, setLevel] = useState(0);
  const active = useRef(true);
  const recRef = useRef<Recognition | null>(null);
  const meterRef = useRef<{ stream: MediaStream; ctx: AudioContext; raf: number } | null>(null);
  const voicesRef = useRef<SpeechSynthesisVoice[]>([]);
  // listen()'s onend fires handleUtterance, which is declared later — go via a
  // ref so the closure always calls the latest (and avoids use-before-declare).
  const utterRef = useRef<(t: string) => void>(() => {});
  // Distinguishes a user "stop/pause" tap from a natural end-of-speech pause, so
  // silence re-arms the mic (keeps the conversation going) but a tap pauses it.
  const stoppedRef = useRef(false);

  const stopMeter = useCallback(() => {
    const m = meterRef.current;
    if (!m) return;
    cancelAnimationFrame(m.raf);
    m.stream.getTracks().forEach((t) => t.stop());
    void m.ctx.close().catch(() => {});
    meterRef.current = null;
    setLevel(0);
  }, []);

  const startMeter = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AC) { stream.getTracks().forEach((t) => t.stop()); return; }
      const ctx = new AC();
      const an = ctx.createAnalyser();
      an.fftSize = 256;
      ctx.createMediaStreamSource(stream).connect(an);
      const data = new Uint8Array(an.frequencyBinCount);
      const tick = () => {
        if (!active.current || !meterRef.current) return;
        an.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i] ?? 0;
        setLevel(Math.min(1, sum / data.length / 140));
        meterRef.current.raf = requestAnimationFrame(tick);
      };
      meterRef.current = { stream, ctx, raf: requestAnimationFrame(tick) };
    } catch {
      /* mic denied — orb just won't react */
    }
  }, []);

  const pickVoice = useCallback((): SpeechSynthesisVoice | undefined => {
    const vs = voicesRef.current;
    if (!vs.length) return undefined;
    const want = [bcp47.toLowerCase(), locale.toLowerCase()];
    const pool = vs.filter((v) => want.some((w) => v.lang?.toLowerCase().startsWith(w)));
    const nice = /natural|neural|online|enhanced|premium|google|siri|aria|jenny|libby|sonia|nova|emma/i;
    return pool.find((v) => nice.test(v.name)) ?? pool[0];
  }, [bcp47, locale]);

  const listen = useCallback(() => {
    const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
    const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!Ctor) { setStatus("unsupported"); return; }
    const rec = new Ctor();
    rec.lang = bcp47;
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;
    let finalText = "";
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (!r) continue;
        if (r.isFinal) finalText += r[0].transcript;
        else interim += r[0].transcript;
      }
      setCaption((finalText + " " + interim).trim());
    };
    rec.onerror = () => {};
    rec.onend = () => {
      stopMeter();
      if (!active.current) return;
      if (stoppedRef.current) { stoppedRef.current = false; setStatus("idle"); return; }
      const t = finalText.trim();
      if (t) { utterRef.current(t); return; }
      // No speech this window — a natural pause. Keep waiting: re-arm the mic so
      // the conversation flows hands-free until the user taps Stop or End.
      window.setTimeout(() => { if (active.current && !stoppedRef.current) listen(); }, 250);
    };
    recRef.current = rec;
    setCaption("");
    setStatus("listening");
    void startMeter();
    try { rec.start(); } catch { /* already starting — ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bcp47, startMeter, stopMeter]);

  const speakReply = useCallback((text: string) => {
    setStatus("speaking");
    if (typeof window === "undefined" || !("speechSynthesis" in window)) { if (active.current) listen(); return; }
    const u = new SpeechSynthesisUtterance(text.replace(/\[source:[^\]]*\]/g, "").replace(/[*_`#>]/g, "").slice(0, 700));
    const v = pickVoice();
    if (v) { u.voice = v; u.lang = v.lang; } else u.lang = bcp47;
    u.rate = 0.98;
    u.onend = () => { if (active.current) listen(); };
    u.onerror = () => { if (active.current) listen(); };
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  }, [pickVoice, bcp47, listen]);

  const handleUtterance = useCallback(async (text: string) => {
    setStatus("thinking");
    setCaption(text);
    let reply = "";
    try { reply = await ask(text); } catch { reply = ""; }
    if (!active.current) return;
    if (reply.trim()) speakReply(reply);
    else setStatus("idle");
  }, [ask, speakReply]);

  utterRef.current = handleUtterance;

  // Start on mount; full teardown on close/unmount.
  useEffect(() => {
    active.current = true;
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      voicesRef.current = window.speechSynthesis.getVoices();
      const load = () => { voicesRef.current = window.speechSynthesis.getVoices(); };
      window.speechSynthesis.addEventListener?.("voiceschanged", load);
    }
    const start = window.setTimeout(() => listen(), 350);
    return () => {
      active.current = false;
      window.clearTimeout(start);
      try { recRef.current?.abort(); } catch { /* noop */ }
      stopMeter();
      if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function close() {
    active.current = false;
    try { recRef.current?.abort(); } catch { /* noop */ }
    stopMeter();
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
    onClose();
  }

  // Tap the orb: interrupt speaking / pause listening / resume.
  function tapOrb() {
    if (status === "speaking") { stoppedRef.current = false; window.speechSynthesis?.cancel(); listen(); return; }
    if (status === "listening") { stoppedRef.current = true; recRef.current?.stop(); return; } // user pause
    stoppedRef.current = false;
    listen();
  }

  const scale = status === "listening" ? 1 + level * 0.6 : 1;
  const ringAnim = status === "speaking" ? "vo-speak 1.4s ease-in-out infinite" : status === "thinking" ? "vo-think 1.2s ease-in-out infinite" : status === "listening" ? undefined : "vo-breathe 4s ease-in-out infinite";

  return (
    <div className="mh mh-force-dark fixed inset-0 z-[60] flex flex-col items-center justify-between bg-[color:var(--mh-bg)] px-6 py-8" role="dialog" aria-label="Voice assistant" style={{ background: "radial-gradient(120% 90% at 50% 15%, color-mix(in srgb, var(--mh-tint) 14%, #000) 0%, #000 60%)" }}>
      <button type="button" onClick={close} aria-label="Close voice" className="mh-circ ghost self-end" style={{ background: "var(--mh-fill)", color: "var(--mh-ink)" }}>
        <X className="h-5 w-5" />
      </button>

      <div className="flex flex-1 flex-col items-center justify-center gap-8">
        {/* Orb */}
        <button type="button" onClick={tapOrb} aria-label="Talk" className="relative grid place-items-center" style={{ width: 240, height: 240 }}>
          <span aria-hidden style={{ position: "absolute", inset: 0, borderRadius: "50%", background: "radial-gradient(circle at 50% 40%, var(--mh-tint-ink), var(--mh-tint-2) 55%, color-mix(in srgb, var(--mh-tint-2) 30%, #000) 100%)", filter: "blur(2px)", transform: `scale(${scale})`, transition: "transform .09s linear", boxShadow: "0 0 80px -10px var(--mh-tint-2)", animation: ringAnim }} />
          <span aria-hidden style={{ position: "absolute", inset: 24, borderRadius: "50%", background: "radial-gradient(circle at 50% 40%, rgba(255,255,255,.35), transparent 60%)", transform: `scale(${scale})`, transition: "transform .09s linear" }} />
          <span aria-hidden style={{ position: "absolute", inset: -18, borderRadius: "50%", border: "1px solid color-mix(in srgb, var(--mh-tint) 40%, transparent)", opacity: status === "listening" ? 0.2 + level * 0.8 : 0.35 }} />
          <Mic className="relative h-10 w-10 text-white/90" />
        </button>

        <div className="min-h-[3.5rem] max-w-md text-center">
          <p className="text-sm font-semibold uppercase tracking-wider text-[color:var(--mh-tint-ink)]">{STATUS_LABEL[status]}</p>
          {caption ? <p className="mt-2 text-lg font-medium text-[color:var(--mh-ink)]">{caption}</p> : status === "idle" ? <p className="mt-2 text-sm text-[color:var(--mh-ink-3)]">Speak naturally — I'll listen, then reply out loud.</p> : null}
        </div>
      </div>

      <div className="flex items-center gap-3 pb-2">
        <button type="button" onClick={tapOrb} className="mh-btn pri" style={{ padding: "12px 22px" }}>
          {status === "listening" ? "Stop" : status === "speaking" ? "Interrupt" : "Talk"}
        </button>
        <button type="button" onClick={close} className="mh-btn ghost" style={{ padding: "12px 22px" }}>End</button>
      </div>
    </div>
  );
}
