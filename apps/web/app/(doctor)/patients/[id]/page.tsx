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
import { Card, CardContent, CardHeader, CardTitle } from "@medagent/ui";

export default async function PatientSessionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const t = await getTranslations("patient");

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">{t("title")}</h1>
        <p className="text-muted-foreground tabular-nums">{t("patientLabel", { id })}</p>
      </div>

      {/* Two-pane session layout (06 §3 FR-2.6). */}
      <div className="grid gap-4 lg:grid-cols-[minmax(280px,1fr)_2fr]">
        <Card aria-label={t("summaryTitle")}>
          <CardHeader>
            <CardTitle>{t("summaryTitle")}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground">{t("summaryPlaceholder")}</p>
          </CardContent>
        </Card>

        <Card aria-label={t("chatTitle")}>
          <CardHeader>
            <CardTitle>{t("chatTitle")}</CardTitle>
          </CardHeader>
          <CardContent>
            {/* role="log" transcript + aria-live streaming status when the
                chat pane lands (06 §4.5, §6). */}
            <p className="text-muted-foreground">{t("chatPlaceholder")}</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
