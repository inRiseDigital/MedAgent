/*
 * Child Health Development Record card (FR-7.x) — the clinician-side render of
 * the CHDR aggregate: consolidated alerts, the EPI immunization schedule as
 * status chips, and the latest growth deviation flags. Server component;
 * shown only for children (see page.tsx gate). Deterministic — no LLM.
 */
import { Baby, Syringe, TrendingUp } from "lucide-react";
import { Card, CardContent } from "@medagent/ui";

import type { ChildHealthRecord } from "@/lib/api";

const IMM_CHIP: Record<string, string> = {
  given: "border-success/40 bg-success-surface text-success",
  overdue: "border-destructive/40 bg-destructive-surface text-destructive",
  "due-soon": "border-warning/40 bg-warning-surface text-warning",
  upcoming: "border-border bg-muted/40 text-muted-foreground",
};

export function ChildHealthCard({ chdr }: { chdr: ChildHealthRecord }) {
  const { immunizations: imm, growth, alerts } = chdr;
  return (
    <Card aria-label="Child health record">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary">
          <Baby className="h-3.5 w-3.5" />
        </span>
        <h2 className="text-sm font-semibold">Child health record</h2>
        {chdr.child.age_months != null ? (
          <span className="ml-auto text-xs tabular-nums text-muted-foreground">
            {chdr.child.age_months.toFixed(1)} months
          </span>
        ) : null}
      </div>
      <CardContent className="space-y-4 p-4">
        {alerts.length > 0 ? (
          <ul className="space-y-1.5">
            {alerts.map((a, i) => (
              <li key={i} className="flex items-start gap-2 text-xs">
                <span
                  aria-hidden
                  className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${a.severity === "block" ? "bg-destructive" : "bg-warning"}`}
                />
                <span className={a.severity === "block" ? "text-destructive" : "text-warning"}>{a.text}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-success">On track — no overdue immunisations or growth deviations.</p>
        )}

        <div>
          <p className="mb-1.5 inline-flex items-center gap-1.5 text-[0.7rem] font-semibold uppercase tracking-wider text-muted-foreground">
            <Syringe className="h-3.5 w-3.5" /> Immunisation (EPI)
          </p>
          <div className="flex flex-wrap gap-1.5">
            {imm.schedule.map((v) => (
              <span
                key={v.key}
                title={v.given_on ? `given ${v.given_on}` : v.due ? `due ${v.due}` : undefined}
                className={`rounded-md border px-2 py-0.5 text-[0.7rem] ${IMM_CHIP[v.status] ?? IMM_CHIP.upcoming}`}
              >
                {v.name.split(" ")[0]} · {v.status}
              </span>
            ))}
          </div>
        </div>

        {growth.points.length > 0 ? (
          <div className="border-t border-border pt-3">
            <p className="mb-1.5 inline-flex items-center gap-1.5 text-[0.7rem] font-semibold uppercase tracking-wider text-muted-foreground">
              <TrendingUp className="h-3.5 w-3.5" /> Growth
            </p>
            {growth.latest_flags.length > 0 ? (
              <p className="text-xs text-destructive">Latest: {growth.latest_flags.join(", ")}</p>
            ) : (
              <p className="text-xs text-muted-foreground">
                Latest measurement within WHO normal range ({growth.points.length} points recorded).
              </p>
            )}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
