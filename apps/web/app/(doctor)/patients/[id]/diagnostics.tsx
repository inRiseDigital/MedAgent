/*
 * Diagnostics cards for the patient session — imaging reports (triaged, urgent-
 * first) and released lab results (critical-flagged). Presentational server
 * components fed by the imaging/lab endpoints. Deterministic triage/flags from
 * core-api; the UI only colour-codes. Theme-aware.
 */
import { FlaskConical, Scan } from "lucide-react";
import { Card, CardContent } from "@medagent/ui";

import type { ImagingReport, LabReport } from "@/lib/api";

const FLAG_STYLE: Record<string, string> = {
  urgent: "text-destructive",
  abnormal: "text-warning",
  normal: "text-muted-foreground",
};

export function ImagingCard({ reports }: { reports: ImagingReport[] }) {
  return (
    <Card aria-label="Imaging">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary">
          <Scan className="h-3.5 w-3.5" />
        </span>
        <h2 className="text-sm font-semibold">Imaging</h2>
      </div>
      <CardContent className="p-3">
        {reports.length === 0 ? (
          <p className="p-2 text-xs text-muted-foreground">No imaging reported.</p>
        ) : (
          <ul className="space-y-1.5">
            {reports.map((r) => (
              <li key={r.ref} className="flex items-start gap-2 text-sm">
                <span
                  aria-hidden
                  className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                    r.flag === "urgent" ? "bg-destructive" : r.flag === "abnormal" ? "bg-warning" : "bg-muted-foreground"
                  }`}
                />
                <span className="min-w-0">
                  <span className="font-medium">{r.code}</span>{" "}
                  <span className={`text-xs uppercase ${FLAG_STYLE[r.flag ?? "normal"] ?? ""}`}>{r.flag}</span>
                  {r.needs_review ? <span className="ml-1 text-xs text-warning">· needs review</span> : null}
                  <span className="block truncate text-xs text-muted-foreground">{r.conclusion}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export function LabResultsCard({ reports }: { reports: LabReport[] }) {
  return (
    <Card aria-label="Lab results">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary">
          <FlaskConical className="h-3.5 w-3.5" />
        </span>
        <h2 className="text-sm font-semibold">Lab results</h2>
      </div>
      <CardContent className="p-3">
        {reports.length === 0 ? (
          <p className="p-2 text-xs text-muted-foreground">No released lab results.</p>
        ) : (
          <ul className="space-y-1.5">
            {reports.map((r) => (
              <li key={r.id} className="flex items-center gap-2 text-sm">
                <span
                  aria-hidden
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${r.critical ? "bg-destructive" : "bg-success"}`}
                />
                <span className="font-medium">{r.test}</span>
                {r.value != null ? (
                  <span className="tabular-nums text-muted-foreground">
                    {r.value} {r.unit}
                  </span>
                ) : null}
                {r.critical ? <span className="text-xs font-semibold uppercase text-destructive">critical</span> : null}
                <span className="ml-auto truncate text-xs text-muted-foreground">{r.conclusion}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
