/*
 * Patient app tab panels (07 §5) — Summary (premium hero + real trend tiles),
 * Record (grouped, tappable rows that ask the concierge), and Me (consent,
 * export, real access log). Server components fed the patient's own data.
 * Plain-language, low-literacy-first. Theme-token driven.
 */
import { Activity, AlertTriangle, CalendarClock, ChevronRight, Download, Droplet, Eye, FileText, FlaskConical, HeartPulse, Pill, ShieldCheck, Thermometer } from "lucide-react";

import type { AccessLogEntry, PatientSummary } from "@/lib/api";
import { LineFade, RangeBar, Ring } from "@/components/charts";
import { ConsentToggle } from "./consent-toggle";
import { Ask } from "./interactive";

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

// The summary returns the latest N observations without deduping by type — keep
// only the most recent reading per measurement (input is already date-desc).
function dedupeVitals(vitals: PatientSummary["vitals"]): PatientSummary["vitals"] {
  const seen = new Set<string>();
  return vitals.filter((v) => {
    if (typeof v.value !== "number" || seen.has(v.text)) return false;
    seen.add(v.text);
    return true;
  });
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

// Premium metric tile: real current value + status; a real line/area trend when
// history exists (never fabricated), else an honest reference-range bar.
function FavTile({ name, value, unit, when, series, gradientId }: { name: string; value: number; unit?: string; when?: string; series?: number[]; gradientId?: string }) {
  const ref = REF.find((r) => r.match.test(name)) ?? null;
  const cat = CAT.find((r) => r.match.test(name));
  const c = cat ? `var(--${cat.c})` : "var(--primary)";
  const Icon = cat?.Icon ?? Activity;
  const out = ref ? value < ref.low || value > ref.high : false;
  const status = ref ? (value < ref.low ? "low" : value > ref.high ? "watch" : "good") : null;
  const statusColor = status === "good" ? "var(--success)" : "var(--warning)";
  const trend = series && series.length >= 2 ? series : null;
  const chartColor = out ? "var(--warning)" : c;
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
      {trend ? (
        <div className="mt-2">
          <LineFade data={trend} color={chartColor} height={56} gradientId={gradientId ?? `lf-${name.replace(/\W+/g, "")}`} />
        </div>
      ) : ref ? (
        <RangeBar value={value} low={ref.low} high={ref.high} color={chartColor} />
      ) : null}
      {when ? <div className="mt-2 text-[0.68rem] font-medium text-muted-foreground">{trend ? "Trend over recent visits" : when.slice(0, 10)}</div> : null}
    </div>
  );
}

export function SummaryView({ summary, trends = {} }: { summary: PatientSummary; trends?: Record<string, number[]> }) {
  const first = summary.patient.name.split(" ")[0] ?? "there";
  const nextAppt = summary.appointments.find((a) => a.start);
  const hasCritical = summary.results.some((r) => r.critical);
  const vitals = dedupeVitals(summary.vitals);
  const fav = vitals.slice(0, 4);
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
            <h3 className="text-xl font-bold tracking-tight">{hasCritical ? "Worth a look" : "On track"}</h3>
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
          <div className="flex items-center gap-3 rounded-2xl p-4 text-white shadow-md" style={{ background: "linear-gradient(150deg, var(--primary), color-mix(in srgb, var(--primary) 55%, #063))" }}>
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
              <FavTile key={i} name={v.text} value={v.value as number} unit={v.unit} when={v.when} series={trends[v.text]} gradientId={`sum-${i}`} />
            ))}
          </div>
        </div>
      ) : null}

      {/* Recent results — tap to have the concierge explain */}
      {summary.results.length > 0 ? (
        <div>
          <SectionLabel>Recent results — tap to explain</SectionLabel>
          <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
            {summary.results.map((r) => (
              <Ask
                key={r.ref}
                question={`Explain my "${r.text}" result (${r.ref}) in simple, reassuring plain language. Say what it means for me and what to do next, and cite it.`}
                className="flex w-full items-center gap-3 border-b border-border/60 p-3.5 text-left transition-colors last:border-0 hover:bg-muted"
              >
                <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${r.critical ? "bg-destructive-surface text-destructive" : "bg-success-surface text-success"}`}>
                  <FlaskConical className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{r.text}</p>
                  {r.conclusion ? <p className="truncate text-xs text-muted-foreground">{r.conclusion}</p> : null}
                </div>
                {r.critical ? <span className="ml-auto shrink-0 rounded-full bg-destructive-surface px-2 py-0.5 text-[0.62rem] font-bold uppercase text-destructive">Critical</span> : null}
                <ChevronRight className="ml-auto h-4 w-4 shrink-0 text-muted-foreground" />
              </Ask>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

// Desktop-only right rail beside the concierge chat — compact at-a-glance.
export function SnapshotRail({ summary, trends = {} }: { summary: PatientSummary; trends?: Record<string, number[]> }) {
  const nextAppt = summary.appointments.find((a) => a.start);
  const vitals = dedupeVitals(summary.vitals).slice(0, 2);
  const critical = summary.results.filter((r) => r.critical);
  return (
    <div className="space-y-4">
      <SectionLabel>At a glance</SectionLabel>
      {critical.length > 0 ? (
        <Ask
          question={`Explain my "${critical[0]?.text}" result in simple, reassuring plain language, and tell me what to do next. Cite it.`}
          className="flex w-full items-start gap-3 rounded-2xl border border-destructive/40 bg-destructive-surface p-4 text-left text-destructive transition hover:brightness-110"
        >
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <p className="text-sm font-semibold">{critical.length} result{critical.length > 1 ? "s" : ""} need{critical.length > 1 ? "" : "s"} attention</p>
            <p className="text-xs opacity-90">{critical.map((r) => r.text).slice(0, 2).join(", ")} — tap to explain</p>
          </div>
        </Ask>
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
        <FavTile key={i} name={v.text} value={v.value as number} unit={v.unit} when={v.when} series={trends[v.text]} gradientId={`rail-${i}`} />
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
  // De-duplicate problems that FHIR sometimes returns more than once.
  const problems = [...new Map(summary.problems.map((p) => [p.text.toLowerCase(), p])).values()];
  const rowCls = "flex w-full items-center gap-3 border-b border-border/60 p-3.5 text-left transition-colors last:border-0 hover:bg-muted";
  return (
    <div className="space-y-5 pt-2">
      <Group label="Allergies — tap to learn more" icon={<AlertTriangle className="h-3.5 w-3.5" />}>
        {summary.allergies.length ? (
          summary.allergies.map((a) => (
            <Ask key={a.ref} question={`What does my "${a.text}" allergy mean for me, and what medicines or things should I avoid? Explain simply.`} className={rowCls}>
              <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${a.criticality === "high" ? "bg-destructive-surface text-destructive" : "bg-warning-surface text-warning"}`}>
                <AlertTriangle className="h-4 w-4" />
              </span>
              <span className="text-sm font-semibold">{a.text}</span>
              {a.criticality === "high" ? <span className="ml-auto shrink-0 rounded-full bg-destructive-surface px-2 py-0.5 text-[0.62rem] font-bold uppercase text-destructive">High risk</span> : null}
              <ChevronRight className="ml-auto h-4 w-4 shrink-0 text-muted-foreground" />
            </Ask>
          ))
        ) : (
          <p className="p-3.5 text-sm text-muted-foreground">No known allergies.</p>
        )}
      </Group>

      <Group label="Medications — tap to learn more" icon={<Pill className="h-3.5 w-3.5" />}>
        {summary.medications.length ? (
          summary.medications.map((m) => (
            <Ask key={m.ref} question={`Tell me about my medication "${m.text}" — what it's for, how to take it, and anything to watch for. Explain simply and cite my record.`} className={rowCls}>
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Pill className="h-4 w-4" /></span>
              <span className="text-sm font-semibold capitalize">{m.text}</span>
              <ChevronRight className="ml-auto h-4 w-4 shrink-0 text-muted-foreground" />
            </Ask>
          ))
        ) : (
          <p className="p-3.5 text-sm text-muted-foreground">None on record.</p>
        )}
      </Group>

      <Group label="Problems — tap to learn more" icon={<HeartPulse className="h-3.5 w-3.5" />}>
        {problems.length ? (
          problems.map((p) => (
            <Ask key={p.ref} question={`Explain my condition "${p.text}" in simple terms — what it means for me and what I should do. Cite my record.`} className={rowCls}>
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground"><HeartPulse className="h-4 w-4" /></span>
              <span className="text-sm font-semibold">{p.text}</span>
              <ChevronRight className="ml-auto h-4 w-4 shrink-0 text-muted-foreground" />
            </Ask>
          ))
        ) : (
          <p className="p-3.5 text-sm text-muted-foreground">None on record.</p>
        )}
      </Group>
    </div>
  );
}

// ---- access-log presentation (turn raw audit rows into plain language) ----
function accessTitle(e: AccessLogEntry): string {
  const a = `${e.action ?? ""} ${e.type ?? ""} ${e.outcome_desc ?? ""}`.toLowerCase();
  if (/export|download/.test(a)) return "You downloaded your record";
  if (/consent/.test(a)) return "Your consent setting changed";
  if (/commit|proposal|prescrib|order|diagnos/.test(a)) return "A clinician updated your record";
  if (/check.?in|queue/.test(a)) return "You were checked in";
  if (/read|view|summary|search|access|get/.test(a)) return "Your record was viewed";
  return "Record activity";
}
function accessIcon(title: string): React.ReactNode {
  if (title.includes("downloaded")) return <Download className="h-4 w-4" />;
  if (title.includes("consent")) return <ShieldCheck className="h-4 w-4" />;
  if (title.includes("clinician")) return <FileText className="h-4 w-4" />;
  return <Eye className="h-4 w-4" />;
}
function relTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return `Today, ${time}`;
  const y = new Date(now);
  y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `Yesterday, ${time}`;
  const days = Math.floor((now.getTime() - d.getTime()) / 86_400_000);
  if (days > 0 && days < 7) return `${days} days ago`;
  return d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

/** Plain-language one-liner for an access-log entry (shared with the concierge). */
export function describeAccess(e: AccessLogEntry): { title: string; when: string } {
  const title = accessTitle(e);
  return { title, when: relTime(e.recorded) };
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
          accessLog.slice(0, 12).map((e, i) => {
            const title = accessTitle(e);
            return (
              <div key={i} className="flex items-center gap-3 border-b border-border/60 p-3.5 last:border-0">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">{accessIcon(title)}</span>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{title}</p>
                  <p className="truncate text-xs text-muted-foreground">{title.startsWith("You") ? "By you" : "By your care team"}</p>
                </div>
                <span className="ml-auto shrink-0 tabular-nums text-xs text-muted-foreground">{relTime(e.recorded)}</span>
              </div>
            );
          })
        ) : (
          <p className="p-3.5 text-sm text-muted-foreground">No recent access recorded.</p>
        )}
      </Group>
    </div>
  );
}
