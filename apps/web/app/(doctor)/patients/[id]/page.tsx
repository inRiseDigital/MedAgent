/*
 * Patient session — record + AI chat side by side (FR-2.6, 06 §3/§6).
 * Left rail: summary card (FR-2.2) from the core-api summary endpoint —
 * demographics, allergy chips (severity-coloured), active problems + meds.
 * Right pane: cited conversational agent. Below: prescription sign-off.
 * Theme-aware; PHN addresses the patient in URL state (06 §5).
 */
import { getTranslations } from "next-intl/server";
import { Clock, FlaskConical, HeartPulse, Pill, Scan, Sparkles } from "lucide-react";
import { Card } from "@medagent/ui";

import {
  fetchChildHealth,
  fetchImagingReports,
  fetchLabReports,
  fetchPatientBrief,
  fetchPatientSummary,
  type ChildHealthRecord,
  type ImagingReport,
  type LabReport,
  type PatientBrief,
  type PatientSummary,
} from "@/lib/api";
import { CLINICAL, requireRoles } from "@/lib/require-role";
import { BodyMap } from "./body-map";
import { ChatPanel } from "./chat-panel";
import { ChildHealthCard } from "./child-health";
import { ClinicianActions } from "./clinician-actions";
import { SideAccordion, type AccordionItem } from "./side-accordion";
import { StatusPanel } from "./status-panel";

function age(birthDate?: string): string {
  if (!birthDate) return "?";
  const b = new Date(birthDate);
  const now = new Date("2026-07-22T00:00:00Z");
  let a = now.getUTCFullYear() - b.getUTCFullYear();
  const m = now.getUTCMonth() - b.getUTCMonth();
  if (m < 0 || (m === 0 && now.getUTCDate() < b.getUTCDate())) a--;
  return String(a);
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[parts.length - 1]?.[0] ?? "")).toUpperCase() || "?";
}

function formatPhn(phn: string): string {
  return phn.length === 11 ? `${phn.slice(0, 3)} ${phn.slice(3, 6)} ${phn.slice(6, 9)} ${phn.slice(9)}` : phn;
}

/** Numbered priority-section header — encodes the clinician's assessment order. */
function PSec({ n, title, hint }: { n: string; title: string; hint?: string }) {
  return (
    <div className="mb-2 mt-1 flex items-center gap-2">
      <span className="flex h-5 w-5 items-center justify-center rounded-md bg-muted text-[0.7rem] font-bold text-primary">{n}</span>
      <h2 className="text-[0.8rem] font-bold uppercase tracking-wide text-muted-foreground">{title}</h2>
      {hint ? <span className="ml-auto text-[0.7rem] text-muted-foreground">{hint}</span> : null}
    </div>
  );
}

export default async function PatientSessionPage({ params }: { params: Promise<{ id: string }> }) {
  await requireRoles(CLINICAL); // clinical record — receptionist bounced to /queue
  const { id } = await params;
  const t = await getTranslations("patient");

  let summary: PatientSummary | null = null;
  let brief: PatientBrief | null = null;
  try {
    summary = await fetchPatientSummary(id);
  } catch {
    summary = null;
  }
  try {
    brief = await fetchPatientBrief(id); // ambient safety flags — best-effort
  } catch {
    brief = null;
  }

  // Child Health Development Record — only for children (under 5). Best-effort.
  const isChild = summary?.patient.birthDate ? Number(age(summary.patient.birthDate)) < 5 : false;
  let chdr: ChildHealthRecord | null = null;
  if (isChild) {
    try {
      chdr = await fetchChildHealth(id);
    } catch {
      chdr = null;
    }
  }

  // Diagnostics (patient-scoped worklists) — best-effort.
  let imaging: ImagingReport[] = [];
  let labs: LabReport[] = [];
  try {
    imaging = (await fetchImagingReports(id)).reports;
  } catch {
    imaging = [];
  }
  try {
    labs = await fetchLabReports(id);
  } catch {
    labs = [];
  }

  const highAllergies = summary?.allergies.filter((a) => a.criticality === "high") ?? [];

  const flags = brief?.flags ?? [];

  // Record accordion — Labs, Imaging, Medications, Problems, Encounters (real data).
  const items: AccordionItem[] = [];
  if (summary) {
    const labRows = [
      ...labs.filter((l) => typeof l.value === "number").map((l) => ({ name: l.test ?? "Lab", val: `${l.value}${l.unit ? " " + l.unit : ""}`, crit: l.critical })),
      ...summary.results.map((r) => ({ name: r.text, val: r.conclusion ?? "", crit: r.critical })),
    ];
    items.push({
      id: "labs",
      title: "Labs & results",
      icon: <FlaskConical className="h-3.5 w-3.5" />,
      badge: labRows.some((r) => r.crit) ? { text: "critical", tone: "destructive" } : undefined,
      content: labRows.length ? (
        <div className="space-y-0.5">
          {labRows.map((r, i) => (
            <div key={i} className="flex items-center gap-2 border-b border-border/60 py-1.5 text-sm last:border-0">
              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${r.crit ? "bg-destructive-surface text-destructive" : "bg-success-surface text-success"}`}><FlaskConical className="h-3.5 w-3.5" /></span>
              <div className="min-w-0"><div className="truncate font-medium">{r.name}</div>{r.val ? <div className="truncate text-xs text-muted-foreground">{r.val}</div> : null}</div>
              {r.crit ? <span className="ml-auto rounded-full bg-destructive-surface px-2 py-0.5 text-[0.58rem] font-bold uppercase text-destructive">critical</span> : null}
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No results on file.</p>
      ),
    });
    items.push({
      id: "imaging",
      title: "Imaging",
      icon: <Scan className="h-3.5 w-3.5" />,
      badge: imaging.some((r) => r.flag === "urgent") ? { text: "urgent", tone: "destructive" } : undefined,
      content: imaging.length ? (
        <div className="space-y-2">
          {imaging.map((r) => (
            <div key={r.ref} className="flex items-center gap-2 text-sm">
              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${r.flag === "urgent" ? "bg-destructive-surface text-destructive" : r.flag === "abnormal" ? "bg-warning-surface text-warning" : "bg-success-surface text-success"}`}><Scan className="h-3.5 w-3.5" /></span>
              <div className="min-w-0"><div className="truncate font-medium">{r.code ?? "Imaging"}</div><div className="truncate text-xs text-muted-foreground">{r.issued?.slice(0, 10) ?? ""}</div></div>
              <span className="ml-auto text-[0.58rem] font-bold uppercase text-muted-foreground">{r.flag ?? "reported"}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No imaging on file.</p>
      ),
    });
    items.push({
      id: "meds",
      title: t("medsLabel"),
      icon: <Pill className="h-3.5 w-3.5" />,
      badge: summary.medications.length ? { text: String(summary.medications.length), tone: "muted" } : undefined,
      content: summary.medications.length ? (
        <ul className="space-y-1 text-sm">{summary.medications.map((m) => (<li key={m.ref} className="flex gap-2"><span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" /><span>{m.text}</span></li>))}</ul>
      ) : (
        <p className="text-xs text-muted-foreground">{t("none")}</p>
      ),
    });
    const problems = [...new Map(summary.problems.map((p) => [p.text.toLowerCase(), p])).values()];
    items.push({
      id: "problems",
      title: t("problemsLabel"),
      icon: <HeartPulse className="h-3.5 w-3.5" />,
      content: problems.length ? (
        <ul className="space-y-1 text-sm">{problems.map((p) => (<li key={p.ref} className="flex gap-2"><span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" /><span>{p.text}</span></li>))}</ul>
      ) : (
        <p className="text-xs text-muted-foreground">{t("none")}</p>
      ),
    });
    const appts = summary.appointments.filter((a) => a.start);
    items.push({
      id: "enc",
      title: "Encounters & timeline",
      icon: <Clock className="h-3.5 w-3.5" />,
      content: appts.length ? (
        <div className="space-y-0.5 text-sm">{appts.map((a, i) => (<div key={i} className="flex items-center gap-2 border-b border-border/60 py-1.5 last:border-0"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-muted text-xs font-bold text-primary">{i + 1}</span><span className="tabular-nums">{a.start ? new Date(a.start).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : ""}</span><span className="ml-auto text-xs text-muted-foreground">{a.status ?? ""}</span></div>))}</div>
      ) : (
        <p className="text-xs text-muted-foreground">No encounters on file.</p>
      ),
    });
    if (chdr) items.push({ id: "chdr", title: "Child health record", icon: <HeartPulse className="h-3.5 w-3.5" />, content: <ChildHealthCard chdr={chdr} /> });
  }

  // Copilot opening brief — proactive safety-first summary from REAL data.
  const opening = summary
    ? {
        greeting: `I've reviewed ${summary.patient.name.split(" ")[0] ?? "this patient"}'s chart — here's what matters before you start.`,
        flags: flags.map((f) => ({ severity: f.severity, text: f.text })),
        ambient:
          `${age(summary.patient.birthDate)}y ${summary.patient.gender ?? ""}`.trim() +
          (summary.problems.length ? `, ${summary.problems.slice(0, 2).map((p) => p.text).join(", ")}` : "") +
          "." +
          (summary.results.some((r) => r.critical)
            ? ` Flagging ${summary.results.filter((r) => r.critical).map((r) => r.text).join(", ")} (critical) — review before prescribing.`
            : " No critical results flagged.") +
          (highAllergies.length ? ` ${highAllergies.map((a) => a.text).join(", ")} allergy on file.` : ""),
      }
    : undefined;

  return (
    <div className="mx-auto max-w-[1500px] space-y-3">
      {/* 1 · Patient */}
      <PSec n="1" title="Patient" hint="the copilot opens with the safety brief below ↓" />
      <div className="flex flex-wrap items-center gap-4 rounded-2xl border border-border bg-card p-4">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary/10 text-base font-semibold text-primary">
          {summary ? initials(summary.patient.name) : "?"}
        </div>
        <div className="min-w-0">
          <h1 className="flex flex-wrap items-center gap-2 text-lg font-semibold leading-tight">
            {summary?.patient.name ?? t("title")}
            {highAllergies.length > 0 ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-destructive/40 bg-destructive-surface px-2.5 py-0.5 text-[0.7rem] font-bold text-destructive">
                <ShieldAlertMini /> {highAllergies.map((a) => a.text).join(", ")} allergy
              </span>
            ) : null}
          </h1>
          <p className="text-xs text-muted-foreground tabular-nums">
            {summary ? (
              <>
                {age(summary.patient.birthDate)}y · {summary.patient.gender ?? "—"} · PHN {formatPhn(summary.patient.phn)}
              </>
            ) : (
              t("patientLabel", { id })
            )}
          </p>
        </div>
        <div className="ml-auto">{summary ? <ClinicianActions patientId={id} videoPhn={summary.patient.phn} /> : null}</div>
      </div>

      {/* Session — copilot (left) · status + record (right) */}
      <div className="grid gap-4 lg:grid-cols-[1fr_minmax(360px,420px)]">
        {/* 3 · Ask — clinical copilot */}
        <main>
          <PSec n="3" title="Ask — clinical copilot" hint="grounded in the chart · cited · safety-screened" />
          <Card aria-label={t("chatTitle")} className="flex min-h-[calc(100dvh-4.5rem)] flex-col overflow-hidden">
            <div className="flex items-center gap-2 border-b border-border px-4 py-3">
              <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary"><Sparkles className="h-3.5 w-3.5" /></span>
              <h2 className="text-sm font-semibold">Copilot</h2>
              {summary ? <span className="ml-auto text-xs text-muted-foreground">{summary.patient.name} · Patient/{id}</span> : null}
            </div>
            <div className="flex min-h-0 flex-1 flex-col">
              <ChatPanel patientId={id} opening={opening} />
            </div>
          </Card>
        </main>

        {/* 2 · Status (body map) + 5 · Record (accordion) */}
        <aside className="lg:sticky lg:top-4 lg:max-h-[calc(100dvh-2rem)] lg:self-start lg:overflow-y-auto lg:pr-1">
          {summary ? (
            <>
              <PSec n="2" title="Status — vitals at a glance" hint="hover a reading" />
              <StatusPanel><BodyMap vitals={summary.vitals} /></StatusPanel>
              <div className="mt-4">
                <PSec n="5" title="Record" hint="open one at a time" />
                <SideAccordion items={items} defaultOpenId="labs" />
              </div>
            </>
          ) : (
            <p className="text-muted-foreground">{t("summaryUnavailable")}</p>
          )}
        </aside>
      </div>
    </div>
  );
}

function ShieldAlertMini() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg>
  );
}
