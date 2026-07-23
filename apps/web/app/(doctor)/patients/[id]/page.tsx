/*
 * Patient session — record + AI chat side by side (FR-2.6) — S1 scaffold,
 * implemented in S3 per docs/solution/11. Target design (06 §3, §6):
 * - Left rail: summary card (FR-2.2 — photo/initials, age, sex, blood
 *   group, allergy chips with severity dots + labels, active meds) fed by
 *   the core-api summary endpoint via @medagent/ts-sdk + TanStack Query.
 * - Right pane: chat on AI SDK `useChat` over /api/chat (cookie → bearer
 *   server-side), rendering typed frames: text / tool status / citation
 *   chips / proposal cards / Rx-safety verdict banners (06 §6–7).
 * - Panes independently scrollable; ≥1280 px design target, tablet stacks
 *   with a pane switcher. Sidebar auto-collapses on entry.
 * Note: 06 §1 names this segment [phn] (patients are addressed by PHN in
 * URL state, 06 §5); S1 scaffolds it as [id] until the MPI lands in S2.
 */
import { getTranslations } from "next-intl/server";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@medagent/ui";
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

export default async function PatientSessionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const t = await getTranslations("patient");

  let summary: PatientSummary | null = null;
  try {
    summary = await fetchPatientSummary(id);
  } catch {
    summary = null;
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">{t("title")}</h1>
        <p className="text-muted-foreground tabular-nums">
          {summary ? `${summary.patient.name} · ${t("patientLabel", { id })}` : t("patientLabel", { id })}
        </p>
      </div>

      {/* Two-pane session layout (06 §3 FR-2.6). */}
      <div className="grid gap-4 lg:grid-cols-[minmax(280px,1fr)_2fr]">
        <Card aria-label={t("summaryTitle")}>
          <CardHeader>
            <CardTitle>{t("summaryTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {!summary ? (
              <p className="text-muted-foreground">{t("summaryUnavailable")}</p>
            ) : (
              <>
                <p className="text-sm">
                  <span className="font-medium">{summary.patient.name}</span>
                  <span className="text-muted-foreground">
                    {" "}· {age(summary.patient.birthDate)}y · {summary.patient.gender ?? "—"}
                  </span>
                </p>
                {summary.allergies.length > 0 ? (
                  <div>
                    <p className="text-2xs uppercase tracking-wide text-muted-foreground">{t("allergiesLabel")}</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {summary.allergies.map((a) => (
                        <Badge key={a.ref} variant={a.criticality === "high" ? "block" : "warn"}>{a.text}</Badge>
                      ))}
                    </div>
                  </div>
                ) : (
                  <p className="text-2xs text-muted-foreground">{t("noAllergiesLabel")}</p>
                )}
                <div>
                  <p className="text-2xs uppercase tracking-wide text-muted-foreground">{t("problemsLabel")}</p>
                  <ul className="mt-1 space-y-0.5 text-sm">
                    {summary.problems.length ? summary.problems.map((p) => <li key={p.ref}>{p.text}</li>)
                      : <li className="text-muted-foreground">{t("none")}</li>}
                  </ul>
                </div>
                <div>
                  <p className="text-2xs uppercase tracking-wide text-muted-foreground">{t("medsLabel")}</p>
                  <ul className="mt-1 space-y-0.5 text-sm">
                    {summary.medications.length ? summary.medications.map((m) => <li key={m.ref}>{m.text}</li>)
                      : <li className="text-muted-foreground">{t("none")}</li>}
                  </ul>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card aria-label={t("chatTitle")}>
          <CardHeader>
            <CardTitle>{t("chatTitle")}</CardTitle>
          </CardHeader>
          <CardContent>
            <ChatPanel patientId={id} />
          </CardContent>
        </Card>
      </div>

      <Card aria-label={t("proposalTitle")}>
        <CardHeader>
          <CardTitle>{t("proposalTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          <ProposalPanel patientId={id} />
        </CardContent>
      </Card>
    </div>
  );
}
