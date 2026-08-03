/*
 * Patient app tab panels (07 §5) — Health (premium summary with clinical
 * reference-range gauges), Record (grouped record), and Me (export, consent,
 * access log). Server components; fed the patient's own data. Plain-language,
 * low-literacy-first. Theme-token driven.
 */
import { Activity, AlertTriangle, CalendarClock, Download, Droplet, FlaskConical, HeartPulse, Pill, ShieldCheck, Thermometer } from "lucide-react";

import type { AccessLogEntry, PatientSummary } from "@/lib/api";
import { RangeBar, Ring } from "@/components/charts";
import { ConsentToggle } from "./consent-toggle";

const REF: { match: RegExp; low: number; high: number }[] = [
  { match: /hba1c|glycated/i, low: 4, high: 5.6 },
  { match: /glucose/i, low: 70, high: 110 },
  { match: /systolic|blood pressure/i, low: 90, high: 140 },
  { match: /heart rate|pulse/i, low: 60, high: 100 },
  { match: /temp/i, low: 36.1, high: 37.5 },
  { match: /oxygen|spo2|sat/i, low: 94, high: 100 },
  { match: /weight/i, low: 45, high: 95 },
];

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <p className="mb-2 ml-1 text-[0.7rem] font-semibold uppercase tracking-wider text-muted-foreground">{children}</p>;
}

// Category colour + icon per metric, so the Favourites tiles read like the demo.
const CAT: { match: RegExp; c: string; Icon: typeof HeartPulse }[] = [
  { match: /hba1c|glyc|glucose|sugar/i, c: "nutri", Icon: Droplet },
  { match: /systolic|diastolic|blood pressure/i, c: "heart", Icon: HeartPulse },
  { match: /heart rate|pulse/i, c: "heart", Icon: Activity },
  { match: /temp/i, c: "nutri", Icon: Thermometer },
  { match: /oxygen|spo2|sat/i, c: "resp", Icon: Activity },
  { match: /weight/i, c: "body", Icon: Activity },
  { match: /potassium|sodium|electrolyte/i, c: "body", Icon: Activity },
];

// Honest metric tile: real current value + status from its reference range, with
// a reference-range bar (no fabricated trend history for single readings).
function FavTile({ name, value, unit, when }: { name: string; value: number; unit?: string; when?: string }) {
  const ref = REF.find((r) => r.match.test(name)) ?? null;
  const cat = CAT.find((r) => r.match.test(name));
  const c = cat ? `var(--${cat.c})` : "var(--primary)";
  const Icon = cat?.Icon ?? Activity;
  const out = ref ? value < ref.low || value > ref.high : false;
  const status = ref ? (value < ref.low ? "low" : value > ref.high ? "watch" : "good") : null;
  const statusColor = status === "good" ? "var(--success)" : "var(--warning)";
  return (
    <div className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg" style={{ background: `color-mix(in srgb, ${c} 16%, transparent)`, color: c }}>
          <Icon className="h-4 w-4" />
        </span>
        <span className="truncate text-[0.8rem] font-semibold">{name}</span>
        {status ? (
          <span className="ml-auto shrink-0 rounded-full px-2 py-0.5 text-[0.6rem] font-bold uppercase" style={{ color: statusColor, background: `color-mix(in srgb, ${statusColor} 15%, transparent)` }}>
            {status}
          </span>
        ) : null}
      </div>
      <div className="mt-2 text-2xl font-bold tabular-nums tracking-tight">
        {value}
        {unit ? <span className="ml-1 text-sm font-semibold text-muted-foreground">{unit}</span> : null}
      </div>
      {ref ? <RangeBar value={value} low={ref.low} high={ref.high} color={out ? "var(--warning)" : c} /> : null}
      {when ? <div className="mt-2 text-[0.68rem] font-medium text-muted-foreground">{when.slice(0, 10)}</div> : null}
    </div>
  );
}

export function SummaryView({ summary }: { summary: PatientSummary }) {
  const first = summary.patient.name.split(" ")[0] ?? "there";
  const nextAppt = summary.appointments.find((a) => a.start);
  const hasCritical = summary.results.some((r) => r.critical);
  const vitals = summary.vitals.filter((v) => typeof v.value === "number");
  const fav = vitals.slice(0, 4);
  // Honest "on track" score: share of reference-gauged vitals within range.
  const gauged = fav
    .map((v) => {
      const ref = REF.find((r) => r.match.test(v.text));
      return ref ? (v.value as number) >= ref.low && (v.value as number) <= ref.high : null;
    })
    .filter((g): g is boolean => g !== null);
  const pct = gauged.length ? Math.round((gauged.filter(Boolean).length / gauged.length) * 100) : 100;
  const ringColor = hasCritical ? "var(--warning)" : "var(--success)";
  return (
    <div className="space-y-6 pt-2">
      {/* Hero — wellbeing ring */}
      <div className="rounded-3xl border border-border bg-card p-5 shadow-sm">
        <div className="flex items-center gap-5">
          <Ring pct={pct} size={116} thickness={14} color={ringColor}>
            <div>
              <div className="text-2xl font-bold tabular-nums leading-none">{pct}%</div>
              <div className="mt-1 text-[0.58rem] font-semibold uppercase tracking-wide text-muted-foreground">in range</div>
            </div>
          </Ring>
          <div className="min-w-0">
            <h3 className="text-xl font-bold tracking-tight">
              {hasCritical ? "Worth a look" : "On track"}
            </h3>
            <p className="mt-1.5 max-w-[26ch] text-sm text-muted-foreground">
              {hasCritical
                ? `${first}, a recent result needs attention — ask the concierge to explain it in plain language.`
                : `Nice work, ${first}. Your recent numbers are within range — keep it up.`}
            </p>
          </div>
        </div>
      </div>

      {/* Your care */}
      {nextAppt ? (
        <div>
          <SectionLabel>Your care</SectionLabel>
          <div
            className="flex items-center gap-3 rounded-2xl p-4 text-white shadow-md"
            style={{ background: "linear-gradient(150deg, var(--primary), color-mix(in srgb, var(--primary) 55%, #063))" }}
          >
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/15">
              <CalendarClock className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <p className="font-semibold">{nextAppt.start ? new Date(nextAppt.start).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "—"}</p>
              <p className="text-sm opacity-90">Next appointment · Teaching Hospital</p>
            </div>
          </div>
        </div>
      ) : null}

      {/* Favourites */}
      {fav.length > 0 ? (
        <div>
          <SectionLabel>Favourites</SectionLabel>
          <div className="grid grid-cols-2 gap-3">
            {fav.map((v, i) => (
              <FavTile key={i} name={v.text} value={v.value as number} unit={v.unit} when={v.when} />
            ))}
          </div>
        </div>
      ) : null}

      {/* Recent results */}
      {summary.results.length > 0 ? (
        <div>
          <SectionLabel>Recent results</SectionLabel>
          <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
            {summary.results.map((r) => (
              <div key={r.ref} className="flex items-center gap-3 border-b border-border/60 p-3.5 last:border-0">
                <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${r.critical ? "bg-destructive-surface text-destructive" : "bg-success-surface text-success"}`}>
                  <FlaskConical className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{r.text}</p>
                  {r.conclusion ? <p className="truncate text-xs text-muted-foreground">{r.conclusion}</p> : null}
                </div>
                {r.critical ? <span className="ml-auto rounded-full bg-destructive-surface px-2 py-0.5 text-[0.62rem] font-bold uppercase text-destructive">Critical</span> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

// Desktop-only right rail shown beside the concierge chat — a compact
// at-a-glance snapshot so the wide screen carries useful context, not emptiness.
export function SnapshotRail({ summary }: { summary: PatientSummary }) {
  const nextAppt = summary.appointments.find((a) => a.start);
  const vitals = summary.vitals.filter((v) => typeof v.value === "number").slice(0, 2);
  const critical = summary.results.filter((r) => r.critical);
  return (
    <div className="space-y-4">
      <SectionLabel>At a glance</SectionLabel>
      {critical.length > 0 ? (
        <div className="flex items-start gap-3 rounded-2xl border border-destructive/40 bg-destructive-surface p-4 text-destructive">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <p className="text-sm font-semibold">{critical.length} result{critical.length > 1 ? "s" : ""} need{critical.length > 1 ? "" : "s"} attention</p>
            <p className="text-xs opacity-90">{critical.map((r) => r.text).slice(0, 2).join(", ")}</p>
          </div>
        </div>
      ) : null}
      {nextAppt ? (
        <div className="flex items-center gap-3 rounded-2xl border border-border bg-card p-4 shadow-sm">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <CalendarClock className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <p className="text-[0.68rem] font-semibold uppercase tracking-wider text-muted-foreground">Next appointment</p>
            <p className="truncate text-sm font-semibold">{nextAppt.start ? new Date(nextAppt.start).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "—"}</p>
          </div>
        </div>
      ) : null}
      {vitals.map((v, i) => (
        <FavTile key={i} name={v.text} value={v.value as number} unit={v.unit} when={v.when} />
      ))}
      <p className="px-1 text-xs text-muted-foreground">Open the <span className="font-semibold text-foreground">Summary</span> tab for your full picture.</p>
    </div>
  );
}

function Group({ label, icon, children }: { label: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <SectionLabel>
        <span className="inline-flex items-center gap-1.5">{icon} {label}</span>
      </SectionLabel>
      <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">{children}</div>
    </div>
  );
}

export function RecordView({ summary }: { summary: PatientSummary }) {
  return (
    <div className="space-y-5 pt-2">
      <Group label="Allergies" icon={<AlertTriangle className="h-3.5 w-3.5" />}>
        {summary.allergies.length ? (
          summary.allergies.map((a) => (
            <div key={a.ref} className="flex items-center gap-3 border-b border-border/60 p-3.5 last:border-0">
              <span className={`flex h-9 w-9 items-center justify-center rounded-lg ${a.criticality === "high" ? "bg-destructive-surface text-destructive" : "bg-warning-surface text-warning"}`}>
                <AlertTriangle className="h-4 w-4" />
              </span>
              <span className="text-sm font-semibold">{a.text}</span>
              {a.criticality === "high" ? <span className="ml-auto rounded-full bg-destructive-surface px-2 py-0.5 text-[0.62rem] font-bold uppercase text-destructive">High risk</span> : null}
            </div>
          ))
        ) : (
          <p className="p-3.5 text-sm text-muted-foreground">No known allergies.</p>
        )}
      </Group>

      <Group label="Medications" icon={<Pill className="h-3.5 w-3.5" />}>
        {summary.medications.length ? (
          summary.medications.map((m) => (
            <div key={m.ref} className="flex items-center gap-3 border-b border-border/60 p-3.5 last:border-0">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary"><Pill className="h-4 w-4" /></span>
              <span className="text-sm font-semibold">{m.text}</span>
            </div>
          ))
        ) : (
          <p className="p-3.5 text-sm text-muted-foreground">None on record.</p>
        )}
      </Group>

      <Group label="Problems" icon={<HeartPulse className="h-3.5 w-3.5" />}>
        {summary.problems.length ? (
          summary.problems.map((p) => (
            <div key={p.ref} className="flex items-center gap-3 border-b border-border/60 p-3.5 last:border-0">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted text-muted-foreground"><HeartPulse className="h-4 w-4" /></span>
              <span className="text-sm font-semibold">{p.text}</span>
            </div>
          ))
        ) : (
          <p className="p-3.5 text-sm text-muted-foreground">None on record.</p>
        )}
      </Group>
    </div>
  );
}

export function MeView({ accessLog }: { accessLog: AccessLogEntry[] }) {
  return (
    <div className="space-y-5 pt-2">
      <Group label="Consent" icon={<ShieldCheck className="h-3.5 w-3.5" />}>
        <div className="p-3.5">
          <ConsentToggle />
        </div>
      </Group>

      <Group label="Download my record" icon={<Download className="h-3.5 w-3.5" />}>
        <div className="flex flex-wrap gap-2 p-3.5">
          <a href="/api/portal/export?format=html" target="_blank" rel="noopener noreferrer" className="rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted">
            Printable summary
          </a>
          <a href="/api/portal/export?format=fhir" className="rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted">
            Portable data (FHIR)
          </a>
        </div>
      </Group>

      <Group label="Who accessed my record" icon={<ShieldCheck className="h-3.5 w-3.5" />}>
        {accessLog.length ? (
          accessLog.slice(0, 12).map((e, i) => (
            <div key={i} className="flex items-center justify-between gap-3 border-b border-border/60 p-3.5 text-sm last:border-0">
              <span className="font-medium">{e.by ?? e.type ?? "Access"}</span>
              <span className="tabular-nums text-xs text-muted-foreground">{e.recorded ? new Date(e.recorded).toLocaleString() : ""}</span>
            </div>
          ))
        ) : (
          <p className="p-3.5 text-sm text-muted-foreground">No recent access recorded.</p>
        )}
      </Group>
    </div>
  );
}
