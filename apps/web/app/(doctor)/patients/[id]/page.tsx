/*
 * Patient session — record + AI chat side by side (FR-2.6, 06 §3/§6).
 * Left rail: summary card (FR-2.2) from the core-api summary endpoint —
 * demographics, allergy chips (severity-coloured), active problems + meds.
 * Right pane: cited conversational agent. Below: prescription sign-off.
 * Theme-aware; PHN addresses the patient in URL state (06 §5).
 */
import { getTranslations } from "next-intl/server";
import { AlertTriangle, ClipboardList, HeartPulse, Pill, ShieldAlert, Siren } from "lucide-react";
import { Badge, Card, CardContent } from "@medagent/ui";

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
import { ChatPanel } from "./chat-panel";
import { ChildHealthCard } from "./child-health";
import { ClinicalEntry } from "./clinical-entry";
import { PatientCockpit } from "./cockpit";
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

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <p className="mb-1.5 text-[0.7rem] font-semibold uppercase tracking-wider text-muted-foreground">{children}</p>;
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
        {highAllergies.length > 0 ? (
          <div className="ml-auto flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive-surface px-3 py-1.5 text-destructive">
            <ShieldAlert className="h-4 w-4 shrink-0" />
            <span className="text-xs font-semibold">
              {highAllergies.map((a) => a.text).join(", ")} allergy
            </span>
          </div>
        ) : null}
      </div>

      {/* Clinician cockpit — vitals & lab gauges + imaging gallery */}
      <PatientCockpit summary={summary} labs={labs} imaging={imaging} />

      {/* Organised session — context rail | work surface */}
      <div className="grid gap-4 lg:grid-cols-[minmax(320px,380px)_1fr]">
        {/* Context rail */}
        <aside className="space-y-4 lg:sticky lg:top-4 lg:self-start">
        <Card aria-label={t("summaryTitle")} className="h-fit">
          <CardContent className="space-y-4 p-4">
            {!summary ? (
              <p className="text-muted-foreground">{t("summaryUnavailable")}</p>
            ) : (
              <>
                {brief && brief.flags.length > 0 ? (
                  <div className="rounded-lg border border-border bg-muted/40 p-3">
                    <SectionLabel>
                      <span className="inline-flex items-center gap-1.5">
                        <Siren className="h-3.5 w-3.5" /> Safety flags
                      </span>
                    </SectionLabel>
                    <ul className="space-y-1.5">
                      {brief.flags.map((f, i) => (
                        <li key={i} className="flex items-start gap-2 text-xs">
                          <span
                            aria-hidden
                            className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                              f.severity === "block" ? "bg-destructive" : f.severity === "warn" ? "bg-warning" : "bg-muted-foreground"
                            }`}
                          />
                          <span className={f.severity === "block" ? "text-destructive" : f.severity === "warn" ? "text-warning" : "text-foreground"}>
                            {f.text}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div>
                  <SectionLabel>
                    <span className="inline-flex items-center gap-1.5">
                      <AlertTriangle className="h-3.5 w-3.5" /> {t("allergiesLabel")}
                    </span>
                  </SectionLabel>
                  {summary.allergies.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {summary.allergies.map((a) => (
                        <Badge key={a.ref} variant={a.criticality === "high" ? "block" : "warn"}>
                          {a.text}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">{t("noAllergiesLabel")}</p>
                  )}
                </div>

                <div className="border-t border-border pt-3">
                  <SectionLabel>
                    <span className="inline-flex items-center gap-1.5">
                      <HeartPulse className="h-3.5 w-3.5" /> {t("problemsLabel")}
                    </span>
                  </SectionLabel>
                  {summary.problems.length ? (
                    <ul className="space-y-1 text-sm">
                      {summary.problems.map((p) => (
                        <li key={p.ref} className="flex gap-2">
                          <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" />
                          <span>{p.text}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-muted-foreground">{t("none")}</p>
                  )}
                </div>

                <div className="border-t border-border pt-3">
                  <SectionLabel>
                    <span className="inline-flex items-center gap-1.5">
                      <Pill className="h-3.5 w-3.5" /> {t("medsLabel")}
                    </span>
                  </SectionLabel>
                  {summary.medications.length ? (
                    <ul className="space-y-1 text-sm">
                      {summary.medications.map((m) => (
                        <li key={m.ref} className="flex gap-2">
                          <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" />
                          <span>{m.text}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-muted-foreground">{t("none")}</p>
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Child Health Development Record — children only, in the context rail */}
        {chdr ? <ChildHealthCard chdr={chdr} /> : null}
        </aside>

        {/* Work surface — AI assistant + clinical write tools */}
        <main className="space-y-4">
          <Card aria-label={t("chatTitle")} className="flex flex-col">
            <div className="flex items-center gap-2 border-b border-border px-4 py-3">
              <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary">
                <HeartPulse className="h-3.5 w-3.5" />
              </span>
              <h2 className="text-sm font-semibold">{t("chatTitle")}</h2>
            </div>
            <div className="p-3">
              <ChatPanel patientId={id} />
            </div>
          </Card>

          {/* Clinical actions — document + prescribe, side by side */}
          <div className="grid gap-4 md:grid-cols-2">
            <Card aria-label="Clinical entry">
              <div className="flex items-center gap-2 border-b border-border px-4 py-3">
                <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <ClipboardList className="h-3.5 w-3.5" />
                </span>
                <h2 className="text-sm font-semibold">Clinical entry</h2>
              </div>
              <CardContent className="p-4">
                <ClinicalEntry patientId={id} />
              </CardContent>
            </Card>

            <Card aria-label={t("proposalTitle")}>
              <div className="flex items-center gap-2 border-b border-border px-4 py-3">
                <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <Pill className="h-3.5 w-3.5" />
                </span>
                <h2 className="text-sm font-semibold">{t("proposalTitle")}</h2>
              </div>
              <CardContent className="p-4">
                <ProposalPanel patientId={id} />
              </CardContent>
            </Card>
          </div>
        </main>
      </div>
    </div>
  );
}
