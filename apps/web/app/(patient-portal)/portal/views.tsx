/*
 * Patient app tab panels (07 §5) — Health (premium summary with clinical
 * reference-range gauges), Record (grouped record), and Me (export, consent,
 * access log). Server components; fed the patient's own data. Plain-language,
 * low-literacy-first. Theme-token driven.
 */
import { AlertTriangle, CalendarClock, Download, FlaskConical, HeartPulse, Pill, ShieldCheck } from "lucide-react";

import type { AccessLogEntry, PatientSummary } from "@/lib/api";
import { RangeBar } from "@/components/charts";
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

function Gauge({ name, value, unit, when }: { name: string; value: number; unit?: string; when?: string }) {
  const ref = REF.find((r) => r.match.test(name)) ?? null;
  const outOfRange = ref ? value < ref.low || value > ref.high : false;
  const color = outOfRange ? "var(--warning)" : "var(--success)";
  const status = ref ? (value < ref.low ? "Low" : value > ref.high ? "High" : "Normal") : null;
  return (
    <div className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-center gap-2">
        <span className="truncate text-[0.78rem] font-semibold text-muted-foreground">{name}</span>
        {status ? (
          <span className="ml-auto rounded-full px-2 py-0.5 text-[0.62rem] font-bold uppercase" style={{ color, background: `color-mix(in srgb, ${color} 15%, transparent)` }}>
            {status}
          </span>
        ) : null}
      </div>
      <div className="mt-1.5 text-2xl font-bold tabular-nums tracking-tight">
        {value}
        {unit ? <span className="ml-1 text-sm font-semibold text-muted-foreground">{unit}</span> : null}
      </div>
      {ref ? <RangeBar value={value} low={ref.low} high={ref.high} color={color} /> : null}
      {when ? <div className="mt-2 text-[0.7rem] font-medium text-muted-foreground">{when.slice(0, 10)}</div> : null}
    </div>
  );
}

export function HealthView({ summary }: { summary: PatientSummary }) {
  const nextAppt = summary.appointments.find((a) => a.start);
  const hasCritical = summary.results.some((r) => r.critical);
  const vitals = summary.vitals.filter((v) => typeof v.value === "number").slice(0, 4);
  return (
    <div className="space-y-5 pt-2">
      <div
        className="rounded-3xl p-5 text-white shadow-lg"
        style={{ background: "linear-gradient(150deg, var(--primary), color-mix(in srgb, var(--primary) 55%, #063))" }}
      >
        <p className="text-xs font-semibold uppercase tracking-wide opacity-80">Good to see you</p>
        <h2 className="mt-1 text-2xl font-bold tracking-tight">{summary.patient.name.split(" ")[0]}</h2>
        <p className="mt-2 max-w-[24ch] text-sm font-medium opacity-95">
          {hasCritical
            ? "A recent result needs your attention — ask the concierge to explain it."
            : "Your record looks on track. Tap the concierge anytime for help."}
        </p>
      </div>

      {nextAppt ? (
        <div className="flex items-center gap-3 rounded-2xl border border-border bg-card p-4 shadow-sm">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <CalendarClock className="h-5 w-5" />
          </span>
          <div>
            <p className="text-[0.7rem] font-semibold uppercase tracking-wider text-muted-foreground">Next appointment</p>
            <p className="font-semibold">{nextAppt.start ? new Date(nextAppt.start).toLocaleString() : "—"}</p>
          </div>
        </div>
      ) : null}

      {vitals.length > 0 ? (
        <div>
          <SectionLabel>Your numbers</SectionLabel>
          <div className="grid grid-cols-2 gap-3">
            {vitals.map((v, i) => (
              <Gauge key={i} name={v.text} value={v.value as number} unit={v.unit} when={v.when} />
            ))}
          </div>
        </div>
      ) : null}

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
