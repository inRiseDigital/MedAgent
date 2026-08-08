/*
 * Patient session — record + AI chat side by side (FR-2.6, 06 §3/§6).
 * Left rail: summary card (FR-2.2) from the core-api summary endpoint —
 * demographics, allergy chips (severity-coloured), active problems + meds.
 * Right pane: cited conversational agent. Below: prescription sign-off.
 * Theme-aware; PHN addresses the patient in URL state (06 §5).
 */
import { getTranslations } from "next-intl/server";
import { Activity, AlertTriangle, ClipboardList, HeartPulse, Pill, ShieldAlert, Siren, Sparkles } from "lucide-react";
import { Badge, Card } from "@medagent/ui";

import {
  fetchChildHealth,
  fetchImagingReports,
  fetchLabReports,
  fetchPatientBrief,
  fetchPatientSummary,
  fetchVitalTrends,
  type ChildHealthRecord,
  type ImagingReport,
  type LabReport,
  type PatientBrief,
  type PatientSummary,
} from "@/lib/api";
import { CLINICAL, requireRoles } from "@/lib/require-role";
import { ChatPanel } from "./chat-panel";
import { ChildHealthCard } from "./child-health";
import { ClinicalEntry } from "./clinical-entry";
import { BodyMap } from "./body-map";
import { PatientCockpit } from "./cockpit";
import { SideAccordion, type AccordionItem } from "./side-accordion";
import { VideoButton } from "./video-button";
import { ProposalPanel } from "./proposal-panel";

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

  // Real vital-sign trend series for the cockpit graphs. Best-effort.
  let trends: Record<string, number[]> = {};
  try {
    const tr = await fetchVitalTrends(id);
    for (const s of tr.series) trends[s.name] = s.points.map((p) => p.value);
  } catch {
    trends = {};
  }

  const flags = brief?.flags ?? [];
  const items: AccordionItem[] = [];
  if (summary) {
    items.push({
      id: "bodymap",
      title: "Vitals — body map",
      icon: <Activity className="h-3.5 w-3.5" />,
      content: <BodyMap vitals={summary.vitals} />,
    });
    if (flags.length) {
      items.push({
        id: "flags",
        title: "Safety flags",
        icon: <Siren className="h-3.5 w-3.5" />,
        badge: { text: String(flags.length), tone: flags.some((f) => f.severity === "block") ? "destructive" : "warning" },
        content: (
          <ul className="space-y-1.5">
            {flags.map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-xs">
                <span aria-hidden className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${f.severity === "block" ? "bg-destructive" : f.severity === "warn" ? "bg-warning" : "bg-muted-foreground"}`} />
                <span className={f.severity === "block" ? "text-destructive" : f.severity === "warn" ? "text-warning" : "text-foreground"}>{f.text}</span>
              </li>
            ))}
          </ul>
        ),
      });
    }
    items.push({
      id: "allergies",
      title: t("allergiesLabel"),
      icon: <AlertTriangle className="h-3.5 w-3.5" />,
      badge: highAllergies.length ? { text: "High risk", tone: "destructive" } : undefined,
      content: summary.allergies.length ? (
        <div className="flex flex-wrap gap-1.5">
          {summary.allergies.map((a) => (
            <Badge key={a.ref} variant={a.criticality === "high" ? "block" : "warn"}>{a.text}</Badge>
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">{t("noAllergiesLabel")}</p>
      ),
    });
    items.push({
      id: "problems",
      title: t("problemsLabel"),
      icon: <HeartPulse className="h-3.5 w-3.5" />,
      content: summary.problems.length ? (
        <ul className="space-y-1 text-sm">
          {summary.problems.map((p) => (
            <li key={p.ref} className="flex gap-2"><span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" /><span>{p.text}</span></li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">{t("none")}</p>
      ),
    });
    items.push({
      id: "meds",
      title: t("medsLabel"),
      icon: <Pill className="h-3.5 w-3.5" />,
      content: summary.medications.length ? (
        <ul className="space-y-1 text-sm">
          {summary.medications.map((m) => (
            <li key={m.ref} className="flex gap-2"><span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" /><span>{m.text}</span></li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">{t("none")}</p>
      ),
    });
  }
  if (chdr) items.push({ id: "chdr", title: "Child health record", icon: <HeartPulse className="h-3.5 w-3.5" />, content: <ChildHealthCard chdr={chdr} /> });

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
  items.push({ id: "entry", title: "Clinical entry", icon: <ClipboardList className="h-3.5 w-3.5" />, content: <ClinicalEntry patientId={id} /> });
  items.push({ id: "rx", title: t("proposalTitle"), icon: <Pill className="h-3.5 w-3.5" />, content: <ProposalPanel patientId={id} /> });

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      {/* Patient banner */}
      <div className="flex flex-wrap items-center gap-4 rounded-lg border border-border bg-card p-4">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary/10 text-base font-semibold text-primary">
          {summary ? initials(summary.patient.name) : "?"}
        </div>
        <div className="min-w-0">
          <h1 className="truncate text-lg font-semibold leading-tight">
            {summary?.patient.name ?? t("title")}
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
        <div className="ml-auto flex items-center gap-2">
          {summary ? <VideoButton phn={summary.patient.phn} /> : null}
          {highAllergies.length > 0 ? (
            <div className="flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive-surface px-3 py-1.5 text-destructive">
              <ShieldAlert className="h-4 w-4 shrink-0" />
              <span className="text-xs font-semibold">
                {highAllergies.map((a) => a.text).join(", ")} allergy
              </span>
            </div>
          ) : null}
        </div>
      </div>

      {/* Clinician cockpit — vitals & lab graphs + imaging gallery */}
      <PatientCockpit summary={summary} labs={labs} imaging={imaging} trends={trends} />

      {/* Session — AI assistant on the LEFT, collapsible record/tools cards on the RIGHT */}
      <div className="grid gap-4 lg:grid-cols-[1fr_minmax(340px,400px)]">
        {/* AI assistant — the primary work surface, left */}
        <main>
          <Card aria-label={t("chatTitle")} className="flex min-h-[calc(100dvh-3rem)] flex-col overflow-hidden">
            <div className="flex items-center gap-2 border-b border-border px-4 py-3">
              <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary">
                <Sparkles className="h-3.5 w-3.5" />
              </span>
              <h2 className="text-sm font-semibold">{t("chatTitle")}</h2>
              <span className="ml-auto text-xs text-muted-foreground">Grounded in the FHIR chart · cited</span>
            </div>
            <div className="flex min-h-0 flex-1 flex-col">
              <ChatPanel patientId={id} opening={opening} />
            </div>
          </Card>
        </main>

        {/* Collapsible cards on the right: safety flags, record detail, write tools */}
        <aside className="lg:sticky lg:top-4 lg:max-h-[calc(100dvh-2rem)] lg:self-start lg:overflow-y-auto lg:pr-1">
          {summary ? (
            <SideAccordion items={items} defaultOpenId="bodymap" />
          ) : (
            <p className="text-muted-foreground">{t("summaryUnavailable")}</p>
          )}
        </aside>
      </div>
    </div>
  );
}
