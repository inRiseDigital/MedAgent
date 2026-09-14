"use client";

/*
 * The Presence — MedAgent's agent, given a body. A living canvas orb that reacts to
 * REAL agent activity: idle (breathing) · listening (ripples) · thinking (inward swirl)
 * · speaking (pulse) · alert (flares red). The chat derives `state` from the live SSE
 * stream (status → thinking, token deltas → speaking, a safety/escalation widget →
 * alert) so the character genuinely acts with the agent, never a scripted loop.
 *
 * Theme-aware (reads --primary / --destructive from the cascade, so it flips with
 * light/dark), and fully still under prefers-reduced-motion.
 */
import { useEffect, useRef } from "react";

export type PresenceState = "idle" | "listening" | "thinking" | "speaking" | "alert";

type Target = { e: number; sw: number; co: number; gl: number; ri: number; rd: number };
const STATES: Record<PresenceState, Target> = {
  idle: { e: 0.14, sw: 0.05, co: 1, gl: 0.9, ri: 0, rd: 0 },
  listening: { e: 0.34, sw: 0.1, co: 1.02, gl: 1, ri: 1, rd: 0 },
  thinking: { e: 0.95, sw: 1, co: 0.96, gl: 1.2, ri: 0.15, rd: 0 },
  speaking: { e: 0.5, sw: 0.25, co: 1.06, gl: 1.05, ri: 0, rd: 0 },
  alert: { e: 1, sw: 0.5, co: 1.1, gl: 1.5, ri: 0.4, rd: 1 },
};

// "#0f766e" | "#fff" -> [r,g,b]; falls back to a teal / rose if a var is missing.
function toRGB(hex: string, fallback: [number, number, number]): [number, number, number] {
  const h = hex.trim().replace("#", "");
  const s = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  if (s.length < 6) return fallback;
  const n = parseInt(s.slice(0, 6), 16);
  if (Number.isNaN(n)) return fallback;
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function Presence({
  state = "idle",
  size = 60,
  className,
}: {
  state?: PresenceState;
  size?: number;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef<PresenceState>(state);
  stateRef.current = state;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const DPR = Math.min(2, window.devicePixelRatio || 1);
    const S = 240; // internal drawing resolution (scaled to `size` by CSS)
    canvas.width = S * DPR;
    canvas.height = S * DPR;
    ctx.scale(DPR, DPR);
    const cx = S / 2;
    const cy = S / 2;

    const cur: Target = { ...STATES.idle };
    const parts = Array.from({ length: 44 }, () => ({
      a: Math.random() * 6.28,
      r: 36 + Math.random() * 52,
      sp: 0.2 + Math.random() * 0.8,
      sz: 0.8 + Math.random() * 1.6,
      ph: Math.random() * 6.28,
    }));
    const ripples: { r: number; a: number }[] = [];
    let t = 0;
    let lastRip = 0;
    let raf = 0;

    const root = document.documentElement;
    const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
    const colorVar = (name: string, fb: [number, number, number]) =>
      toRGB(getComputedStyle(root).getPropertyValue(name), fb);

    const frame = () => {
      t += 1;
      const tgt = STATES[stateRef.current] ?? STATES.idle;
      const speaking = stateRef.current === "speaking";
      const k = reduce ? 1 : 0.08;
      (Object.keys(tgt) as (keyof Target)[]).forEach((key) => {
        cur[key] = lerp(cur[key], tgt[key], k);
      });
      const p = colorVar("--primary", [45, 212, 191]);
      const d = colorVar("--destructive", [255, 86, 111]);
      const rgb = p.map((v, i) => Math.round(lerp(v, d[i]!, cur.rd))).join(",");
      const breathe = 1 + Math.sin(t * 0.03 * (1 + cur.e)) * (0.03 + cur.e * 0.05);

      ctx.clearRect(0, 0, S, S);
      // glow
      const g = ctx.createRadialGradient(cx, cy, 8, cx, cy, 100 * cur.gl * breathe);
      g.addColorStop(0, `rgba(${rgb},${0.3 + cur.e * 0.25})`);
      g.addColorStop(0.5, `rgba(${rgb},0.1)`);
      g.addColorStop(1, `rgba(${rgb},0)`);
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, S, S);
      // ripples (listening / alert)
      if (!reduce && cur.ri > 0.2 && t - lastRip > 26 - cur.ri * 10) {
        ripples.push({ r: 30, a: 0.5 });
        lastRip = t;
      }
      for (let j = ripples.length - 1; j >= 0; j--) {
        const R = ripples[j]!;
        R.r += 1.6;
        R.a -= 0.012;
        if (R.a <= 0) {
          ripples.splice(j, 1);
          continue;
        }
        ctx.beginPath();
        ctx.arc(cx, cy, R.r, 0, 6.283);
        ctx.strokeStyle = `rgba(${rgb},${R.a})`;
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      // orbiting particles
      for (const pt of parts) {
        if (!reduce) pt.a += 0.004 + pt.sp * 0.01 * cur.e + cur.sw * 0.02;
        const pr = pt.r - cur.sw * Math.sin(t * 0.02 + pt.ph) * 10 * cur.e;
        const x = cx + Math.cos(pt.a) * pr;
        const y = cy + Math.sin(pt.a) * pr * 0.96;
        const tw = 0.4 + 0.6 * Math.abs(Math.sin(t * 0.05 + pt.ph));
        ctx.beginPath();
        ctx.arc(x, y, pt.sz * (0.6 + cur.e * 0.7), 0, 6.283);
        ctx.fillStyle = `rgba(${rgb},${0.15 + tw * 0.55 * cur.e})`;
        ctx.fill();
      }
      // core
      const pulse = speaking ? 1 + Math.sin(t * 0.28) * 0.06 : 1;
      const coreR = 30 * cur.co * breathe * pulse;
      const cg = ctx.createRadialGradient(cx - coreR * 0.3, cy - coreR * 0.3, 2, cx, cy, coreR);
      cg.addColorStop(0, "rgba(255,255,255,0.92)");
      cg.addColorStop(0.35, `rgba(${rgb},0.95)`);
      cg.addColorStop(1, `rgba(${rgb},0.22)`);
      ctx.beginPath();
      ctx.arc(cx, cy, coreR, 0, 6.283);
      ctx.fillStyle = cg;
      ctx.fill();

      if (!reduce) raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    if (reduce) frame(); // one static paint

    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className={className}
      aria-hidden="true"
      style={{ width: size, height: size, display: "block" }}
    />
  );
}
