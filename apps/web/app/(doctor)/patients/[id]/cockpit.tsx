/*
 * Clinician cockpit (06 §3) — a professional dashboard band at the top of the
 * patient session: latest vitals & labs as clinical reference-range gauges
 * (value-vs-normal, real data — no fabricated trends), and an imaging gallery
 * with the real AI-triage flags from /imaging/reports. Server component.
 */
import { AlertTriangle, Scan } from "lucide-react";

import type { ImagingReport, LabReport, PatientSummary } from "@/lib/api";
import { LineFade, RangeBar } from "@/components/charts";

// Curated reference ranges (clinician-owned in prod). Keyed by substring match on
// the measurement name/unit; used only to place the value on its normal band.
const REF: { match: RegExp; low: number; high: number; label: string }[] = [
  { match: /hba1c|glycated/i, low: 4, high: 5.6, label: "%" },
  { match: /glucose/i, low: 70, high: 110, label: "mg/dL" },
  { match: /systolic|blood pressure/i, low: 90, high: 140, label: "mmHg" },
  { match: /heart rate|pulse/i, low: 60, high: 100, label: "bpm" },
  { match: /temp/i, low: 36.1, high: 37.5, label: "°C" },
  { match: /oxygen|spo2|sat/i, low: 94, high: 100, label: "%" },
  { match: /potassium/i, low: 3.5, high: 5.1, label: "mmol/L" },
  { match: /sodium/i, low: 135, high: 145, label: "mmol/L" },
  { match: /creatinine/i, low: 60, high: 110, label: "µmol/L" },
  { match: /h(ae)?moglobin|\bhb\b/i, low: 12, high: 17, label: "g/dL" },
  { match: /platelet/i, low: 150, high: 400, label: "×10⁹" },
];

function refFor(name: string) {
  return REF.find((r) => r.match.test(name)) ?? null;
}

/** value color: within band → success, outside → warning/destructive by distance */
function statusColor(v: number, low: number, high: number, critical?: boolean): string {
  if (critical) return "var(--destructive)";
  if (v < low || v > high) return "var(--warning)";
  return "var(--success)";
}

function GaugeTile({ name, value, unit, when, critical, series, gradientId }: { name: string; value: number; unit?: string; when?: string; critical?: boolean; series?: number[]; gradientId?: string }) {
  const ref = refFor(name);
  const color = ref ? statusColor(value, ref.low, ref.high, critical) : "var(--primary)";
  const status = critical ? "Critical" : ref ? (value < ref.low ? "Low" : value > ref.high ? "High" : "Normal") : null;
  const trend = series && series.length >= 2 ? series : null;
  return (
    <div className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-center gap-2">
        <span className="truncate text-[0.78rem] font-semibold text-muted-foreground">{name}</span>
        {status ? (
          <span
            className="ml-auto rounded-full px-2 py-0.5 text-[0.62rem] font-bold uppercase tracking-wide"
            style={{ color, background: `color-mix(in srgb, ${color} 15%, transparent)` }}
          >
            {status}
          </span>
        ) : null}
      </div>
      <div className="mt-1.5 text-2xl font-bold tabular-nums tracking-tight">
        {value}
        {unit ? <span className="ml-1 text-sm font-semibold text-muted-foreground">{unit}</span> : null}
      </div>
      {trend ? (
        <div className="mt-2"><LineFade data={trend} color={color} height={52} gradientId={gradientId ?? `g-${name.replace(/\W+/g, "")}`} /></div>
      ) : ref ? (
        <RangeBar value={value} low={ref.low} high={ref.high} color={color} />
      ) : null}
      {when ? <div className="mt-2 text-[0.7rem] font-medium text-muted-foreground">{trend ? "Trend over recent visits" : when.slice(0, 10)}</div> : null}
    </div>
  );
}

/** Stylised radiograph thumbnail (no real image — a clean imaging placeholder). */
function FilmThumb({ report }: { report: ImagingReport }) {
  const urgent = report.flag === "urgent";
  const chip = urgent
    ? { t: "Urgent", c: "var(--destructive)" }
    : report.flag === "abnormal"
      ? { t: report.needs_review ? "Review" : "Abnormal", c: "var(--warning)" }
      : { t: "Normal", c: "var(--success)" };
  return (
    <div className="relative w-[150px] shrink-0 overflow-hidden rounded-2xl shadow-sm" style={{ background: "#05070a" }}>
      <svg viewBox="0 0 150 168" width="150" height="168" style={{ display: "block" }}>
        <defs>
          <radialGradient id={`f-${report.ref.replace(/[^a-z0-9]/gi, "")}`} cx="50%" cy="42%" r="72%">
            <stop offset="0" stopColor="#1c2c3c" />
            <stop offset="1" stopColor="#05080c" />
          </radialGradient>
        </defs>
        <rect width="150" height="168" fill={`url(#f-${report.ref.replace(/[^a-z0-9]/gi, "")})`} />
        <ellipse cx="52" cy="84" rx="26" ry="42" fill="#33465a" opacity={urgent ? 0.5 : 0.78} />
        <ellipse cx="98" cy="84" rx="26" ry="42" fill="#33465a" opacity={0.78} />
        <rect x="72" y="38" width="6" height="96" rx="3" fill="#4a6076" opacity="0.5" />
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <path key={i} d={`M40 ${52 + i * 12} Q75 ${44 + i * 12} 110 ${52 + i * 12}`} stroke="#5a7288" strokeWidth="1.3" fill="none" opacity="0.32" />
        ))}
        {urgent ? <path d="M30 58 Q40 100 46 132" stroke="var(--destructive)" strokeWidth="2" fill="none" opacity="0.85" /> : null}
      </svg>
      <span
        className="absolute left-2 top-2 rounded-full px-2 py-1 text-[0.6rem] font-bold uppercase tracking-wide text-white"
        style={{ background: chip.c }}
      >
        {chip.t}
      </span>
      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 to-transparent p-2">
        <div className="text-xs font-bold text-white">{report.code ?? "Imaging"}</div>
        <div className="text-[0.65rem] text-white/70">{report.issued?.slice(0, 10) ?? ""}</div>
      </div>
    </div>
  );
}

export function PatientCockpit({
  summary,
  labs,
  imaging,
  trends = {},
}: {
  summary: PatientSummary | null;
  labs: LabReport[];
  imaging: ImagingReport[];
  trends?: Record<string, number[]>;
}) {
  // Latest reading per measurement (FHIR returns duplicates across visits) → one
  // tile each; a real trend line where history exists, else a reference-range bar.
  const seenV = new Set<string>();
  const vitalTiles = (summary?.vitals ?? [])
    .filter((v) => typeof v.value === "number" && !seenV.has(v.text) && seenV.add(v.text))
    .slice(0, 4);
  const seenL = new Set<string>();
  const labTiles = labs
    .filter((l) => typeof l.value === "number" && !!l.test && !seenL.has(l.test) && seenL.add(l.test))
    .slice(0, 4);
  const hasGauges = vitalTiles.length + labTiles.length > 0;

  return (
    <div className="space-y-4">
      {hasGauges ? (
        <div>
          <p className="mb-2 ml-1 text-[0.7rem] font-semibold uppercase tracking-wider text-muted-foreground">Vitals &amp; labs</p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {vitalTiles.map((v, i) => (
              <GaugeTile key={`v${i}`} name={v.text} value={v.value as number} unit={v.unit} when={v.when} series={trends[v.text]} gradientId={`ck-v${i}`} />
            ))}
            {labTiles.map((l) => (
              <GaugeTile key={l.id} name={l.test ?? "Lab"} value={l.value as number} unit={l.unit} when={l.issued} critical={l.critical} series={l.test ? trends[l.test] : undefined} gradientId={`ck-l${l.id}`} />
            ))}
          </div>
        </div>
      ) : null}

      {imaging.length > 0 ? (
        <div>
          <p className="mb-2 ml-1 inline-flex items-center gap-1.5 text-[0.7rem] font-semibold uppercase tracking-wider text-muted-foreground">
            <Scan className="h-3.5 w-3.5" /> Imaging
            {imaging.some((r) => r.flag === "urgent") ? (
              <span className="ml-1 inline-flex items-center gap-1 rounded-full bg-destructive-surface px-2 py-0.5 text-[0.62rem] font-bold text-destructive">
                <AlertTriangle className="h-3 w-3" /> Urgent finding
              </span>
            ) : null}
          </p>
          <div className="flex gap-3 overflow-x-auto pb-1">
            {imaging.map((r) => (
              <FilmThumb key={r.ref} report={r} />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
