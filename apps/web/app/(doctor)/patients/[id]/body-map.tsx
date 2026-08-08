/*
 * Body map (06 §3) — an anatomical at-a-glance of the patient's vitals: each
 * recognised reading is pinned at its organ site and colour-coded against its
 * reference range (green in-range / amber out), with a tile grid beneath. Real
 * data only — pins render only for vitals actually on file. Server component;
 * collapsed/expanded by the record accordion it lives in.
 */
const COL = { good: "#3ad884", watch: "#ffab3d" };

// vital name → anatomical pin site + reference range + display side
const SITES: { re: RegExp; x: number; y: number; side: "L" | "R"; low: number; high: number; label: string }[] = [
  { re: /heart rate|pulse/i, x: 243, y: 214, side: "L", low: 60, high: 100, label: "Heart rate" },
  { re: /systolic|blood pressure/i, x: 280, y: 214, side: "R", low: 90, high: 140, label: "Blood pressure" },
  { re: /oxygen|spo2|sat/i, x: 288, y: 166, side: "R", low: 94, high: 100, label: "SpO₂" },
  { re: /resp/i, x: 232, y: 150, side: "L", low: 12, high: 20, label: "Resp rate" },
  { re: /temp/i, x: 260, y: 52, side: "L", low: 36.1, high: 37.5, label: "Temp" },
  { re: /weight/i, x: 260, y: 268, side: "R", low: 45, high: 95, label: "Weight" },
];

type Pin = { x: number; y: number; side: "L" | "R"; label: string; value: number; unit?: string; col: string; out: boolean };

export function BodyMap({ vitals }: { vitals: { text: string; value?: number; unit?: string }[] }) {
  const seen = new Set<string>();
  const list = vitals.filter((v) => typeof v.value === "number" && !seen.has(v.text) && seen.add(v.text));

  const pins: Pin[] = [];
  for (const v of list) {
    const s = SITES.find((si) => si.re.test(v.text));
    if (!s) continue;
    const val = v.value as number;
    const out = val < s.low || val > s.high;
    pins.push({ x: s.x, y: s.y, side: s.side, label: s.label, value: val, unit: v.unit, col: out ? COL.watch : COL.good, out });
  }

  return (
    <div>
      <svg viewBox="0 0 520 470" width="100%" style={{ display: "block" }}>
        <defs>
          <radialGradient id="bmbg" cx="50%" cy="30%" r="70%">
            <stop offset="0" stopColor="#1a2733" />
            <stop offset="1" stopColor="#0c1116" />
          </radialGradient>
        </defs>
        <rect x="150" y="0" width="220" height="470" rx="60" fill="url(#bmbg)" opacity="0.35" />
        {/* figure */}
        <g fill="#2b3947" stroke="#3f5266" strokeWidth="1.5" opacity="0.92">
          <circle cx="260" cy="60" r="34" />
          <rect x="250" y="92" width="20" height="16" rx="6" />
          <path d="M205 118 Q260 100 315 118 L332 150 Q334 220 320 300 L300 300 Q290 210 292 150 L228 150 Q230 210 220 300 L200 300 Q186 220 188 150 Z" />
          <path d="M332 150 Q360 200 356 270 L342 272 Q338 210 320 168 Z" />
          <path d="M188 150 Q160 200 164 270 L178 272 Q182 210 200 168 Z" />
          <path d="M228 300 Q232 380 236 452 L258 452 Q262 380 258 300 Z" />
          <path d="M292 300 Q288 380 284 452 L262 452 Q258 380 262 300 Z" />
        </g>
        {/* heart tint by heart-rate status if present */}
        {pins.filter((p) => p.label === "Heart rate").map((p, i) => (
          <path key={`h${i}`} d="M246 176 q-9 -10 -17 -1 q-7 9 17 24 q24 -15 17 -24 q-8 -9 -17 1z" fill={p.col} fillOpacity="0.28" />
        ))}
        {/* pins + connectors + label pills */}
        {pins.map((p, i) => {
          const lx = p.side === "L" ? 22 : 398;
          const x1 = p.side === "L" ? lx + 110 : lx;
          return (
            <g key={i}>
              <line x1={x1} y1={p.y} x2={p.x} y2={p.y} stroke={p.col} strokeOpacity="0.5" strokeWidth="1.4" />
              <circle cx={p.x} cy={p.y} r="9" fill={p.col} fillOpacity="0.18" />
              <circle cx={p.x} cy={p.y} r="4" fill={p.col} />
              <g transform={`translate(${lx},${p.y - 15})`}>
                <rect width="110" height="30" rx="9" fill="#0f1114" stroke={p.col} strokeOpacity="0.55" />
                <text x="9" y="12" fill="#8b95a1" fontSize="8" fontWeight="800">{p.label.toUpperCase()}</text>
                <text x="9" y="24" fill={p.col} fontSize="12.5" fontWeight="800">
                  {p.value} <tspan fill="#727a84" fontSize="8">{p.unit ?? ""}</tspan>
                </text>
              </g>
            </g>
          );
        })}
        {pins.length === 0 ? (
          <text x="260" y="240" textAnchor="middle" fill="#727a84" fontSize="12">No vitals on file</text>
        ) : null}
      </svg>

      {list.length > 0 ? (
        <div className="mt-2 grid grid-cols-2 gap-2">
          {list.map((v, i) => {
            const s = SITES.find((si) => si.re.test(v.text));
            const out = s ? (v.value as number) < s.low || (v.value as number) > s.high : false;
            const color = out ? "var(--warning)" : "var(--success)";
            return (
              <div key={i} className="rounded-xl border border-border bg-muted/40 p-2.5">
                <div className="truncate text-[0.66rem] font-bold uppercase tracking-wide text-muted-foreground">{v.text}</div>
                <div className="mt-0.5 text-lg font-bold tabular-nums">
                  {v.value}
                  {v.unit ? <span className="ml-1 text-[0.66rem] font-semibold text-muted-foreground">{v.unit}</span> : null}
                </div>
                {s ? (
                  <span className="mt-1 inline-block rounded-full px-1.5 py-0.5 text-[0.56rem] font-bold uppercase" style={{ color, background: `color-mix(in srgb, ${color} 15%, transparent)` }}>
                    {out ? "watch" : "normal"}
                  </span>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
