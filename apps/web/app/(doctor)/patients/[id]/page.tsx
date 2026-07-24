/*
 * Patient session — record + AI chat side by side (FR-2.6, 06 §3/§6).
 * Left rail: summary card (FR-2.2) from the core-api summary endpoint —
 * demographics, allergy chips (severity-coloured), active problems + meds.
 * Right pane: cited conversational agent. Below: prescription sign-off.
 * Theme-aware; PHN addresses the patient in URL state (06 §5).
 */
import { getTranslations } from "next-intl/server";
import { AlertTriangle, HeartPulse, Pill, ShieldAlert } from "lucide-react";
import { Badge, Card, CardContent } from "@medagent/ui";

import { fetchPatientSummary, type PatientSummary } from "@/lib/api";
import { ChatPanel } from "./chat-panel";
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
  const { id } = await params;
  const t = await getTranslations("patient");

  let summary: PatientSummary | null = null;
  try {
    summary = await fetchPatientSummary(id);
  } catch {
    summary = null;
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

      {/* Two-pane session layout */}
      <div className="grid gap-4 lg:grid-cols-[minmax(300px,1fr)_1.9fr]">
        {/* Summary rail */}
        <Card aria-label={t("summaryTitle")} className="h-fit">
          <CardContent className="space-y-4 p-4">
            {!summary ? (
              <p className="text-muted-foreground">{t("summaryUnavailable")}</p>
            ) : (
              <>
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

        {/* Chat */}
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
      </div>

      {/* Prescription sign-off */}
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
  );
}
