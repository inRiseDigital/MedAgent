/*
 * Premium data-viz primitives (06 §4) — pure SVG, server-renderable, theme-token
 * driven so light/dark and the design palette flow through automatically. Used by
 * the clinician cockpit and the patient app. No external chart library (keeps the
 * bundle small and the CSP clean).
 */
import type { ReactNode } from "react";

const TRACK = "color-mix(in srgb, var(--foreground) 10%, transparent)";
const FAINT = "color-mix(in srgb, var(--foreground) 12%, transparent)";

/** A progress / gauge ring with optional centred content. */
export function Ring({
  pct,
  size = 120,
  thickness = 14,
  color = "var(--primary)",
  children,
}: {
  pct: number;
  size?: number;
  thickness?: number;
  color?: string;
  children?: ReactNode;
}) {
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  const off = c * (1 - Math.min(100, Math.max(0, pct)) / 100);
  return (
    <div style={{ position: "relative", width: size, height: size, flex: "none" }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={TRACK} strokeWidth={thickness} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={thickness}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={off}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      {children ? (
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", textAlign: "center" }}>
          {children}
        </div>
      ) : null}
    </div>
  );
}

/** Minimal trend line (no axes) for metric tiles. */
export function Sparkline({ data, color = "var(--primary)", height = 36 }: { data: number[]; color?: string; height?: number }) {
  if (data.length < 2) return <svg style={{ width: "100%", height }} />;
  const w = 100;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const rng = max - min || 1;
  const pts = data
    .map((p, i) => `${((i / (data.length - 1)) * w).toFixed(1)},${(height - 3 - ((p - min) / rng) * (height - 6)).toFixed(1)}`)
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" style={{ width: "100%", height }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** Bar chart with optional day labels and a highlighted bar. */
export function Bars({
  data,
  labels,
  activeIndex = data.length - 1,
  color = "var(--primary)",
  height = 88,
}: {
  data: number[];
  labels?: string[];
  activeIndex?: number;
  color?: string;
  height?: number;
}) {
  const W = 300;
  const H = height;
  const n = data.length || 1;
  const g = 9;
  const bw = (W - g * (n - 1)) / n;
  const max = Math.max(...data, 1);
  const base = labels ? 24 : 4;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height }}>
      {data.map((v, i) => {
        const bh = Math.max(6, (v / max) * (H - base - 4));
        const x = i * (bw + g);
        const y = H - base - bh;
        return <rect key={i} x={x} y={y} width={bw} height={bh} rx={Math.min(bw / 2.4, 8)} fill={i === activeIndex ? color : FAINT} />;
      })}
      {labels?.map((l, i) => (
        <text key={i} x={i * (bw + g) + bw / 2} y={H - 4} textAnchor="middle" fontSize="10" fontWeight="700" fill="var(--muted-foreground)">
          {l}
        </text>
      ))}
    </svg>
  );
}

/** Clinical reference-range bar: shows the normal band and where the value sits.
 * Honest for single readings (no fabricated history) and instantly readable. */
export function RangeBar({ value, low, high, color = "var(--primary)" }: { value: number; low: number; high: number; color?: string }) {
  const span = high - low || 1;
  const min = low - span * 0.45;
  const max = high + span * 0.45;
  const clamp = (n: number) => Math.min(100, Math.max(0, n));
  const pos = clamp(((value - min) / (max - min)) * 100);
  const lowPct = clamp(((low - min) / (max - min)) * 100);
  const highPct = clamp(((high - min) / (max - min)) * 100);
  return (
    <div style={{ position: "relative", height: 8, borderRadius: 999, background: FAINT, marginTop: 10 }}>
      <div
        style={{
          position: "absolute",
          left: `${lowPct}%`,
          width: `${highPct - lowPct}%`,
          top: 0,
          bottom: 0,
          background: "color-mix(in srgb, var(--success) 34%, transparent)",
          borderRadius: 999,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: `${pos}%`,
          top: -3,
          width: 14,
          height: 14,
          marginLeft: -7,
          borderRadius: "50%",
          background: color,
          border: "2px solid var(--card)",
          boxShadow: "0 1px 3px rgba(0,0,0,.3)",
        }}
      />
    </div>
  );
}

/** Smooth-ish line with a gradient area fill and an emphasised endpoint. */
export function LineFade({
  data,
  labels,
  color = "var(--primary)",
  height = 112,
  gradientId,
}: {
  data: number[];
  labels?: string[];
  color?: string;
  height?: number;
  gradientId: string;
}) {
  if (data.length < 2) return <svg style={{ width: "100%", height }} />;
  const W = 300;
  const pad = 8;
  const plotH = height - (labels ? 16 : 6);
  const min = Math.min(...data);
  const max = Math.max(...data);
  const rng = max - min || 1;
  const xy = data.map((p, i): [number, number] => [
    pad + (i / (data.length - 1)) * (W - 2 * pad),
    plotH - pad - ((p - min) / rng) * (plotH - 2 * pad),
  ]);
  const line = xy.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const area = `${pad},${plotH - pad} ${line} ${W - pad},${plotH - pad}`;
  const last = xy[xy.length - 1]!;
  return (
    <svg viewBox={`0 0 ${W} ${height}`} style={{ width: "100%", height }}>
      <defs>
        <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.28" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#${gradientId})`} />
      <polyline points={line} fill="none" stroke={color} strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r={4.5} fill={color} stroke="var(--card)" strokeWidth={2.5} />
      {labels?.map((l, i) => (
        <text key={i} x={xy[i]![0]} y={height - 2} textAnchor="middle" fontSize="9" fontWeight="700" fill="var(--muted-foreground)">
          {l}
        </text>
      ))}
    </svg>
  );
}
