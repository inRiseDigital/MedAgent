/*
 * Patient portal home (FR-5, 07 §5) — now a chat-first app: the Concierge is the
 * default tab, with Health / Record / Me alongside. The patient is resolved from
 * the `phn` session claim (02 §8.5) and only ever sees their own compartment.
 * Data is fetched server-side and handed to the client shell.
 */
import {
  fetchAccessLog,
  fetchImmunizations,
  fetchPatientSummary,
  fetchVitalTrends,
  type AccessLogEntry,
  type PatientSummary,
} from "@/lib/api";
import { getSession } from "@/lib/session-store";
import { Concierge } from "./concierge";
import { PatientApp } from "./patient-app";
import { describeAccess, MeView, RecordView, SnapshotRail, SummaryView } from "./views";

export const dynamic = "force-dynamic";

export default async function PortalHomePage() {
  const session = await getSession();
  const phn = session?.patientPhn;

  let summary: PatientSummary | null = null;
  let accessLog: AccessLogEntry[] = [];
  if (phn) {
    try {
      [summary, accessLog] = await Promise.all([fetchPatientSummary(phn), fetchAccessLog(phn)]);
    } catch {
      summary = null;
    }
  }

  if (!phn || !summary) {
    return (
      <div className="mx-auto mt-6 max-w-md rounded-2xl border border-border bg-card p-6 text-center">
        <p className="text-muted-foreground">
          {!phn
            ? "No linked patient record for this account."
            : "We couldn't load your record right now — the service may be starting up."}
        </p>
        {phn ? (
          <a href="/portal" className="mt-4 inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:brightness-110">
            Try again
          </a>
        ) : null}
      </div>
    );
  }

  // Real, record-derived signals for the concierge greeting (no scripted fiction).
  const bd = summary.patient.birthDate;
  const ageYears = bd ? Math.floor((Date.now() - Date.parse(bd)) / 31_557_600_000) : null;
  // EPI immunisations only make sense for children — never show "overdue vaccine"
  // nudges for an adult (the schedule would flag decades-old childhood doses).
  let overdueVaccines: string[] = [];
  if (ageYears !== null && ageYears < 6) {
    try {
      const imm = await fetchImmunizations(phn);
      overdueVaccines = imm.schedule.filter((r) => r.status === "overdue").map((r) => r.name).slice(0, 4);
    } catch {
      overdueVaccines = [];
    }
  }
  // Real vital-sign trend series (for the premium line/area tiles). Best-effort.
  let trends: Record<string, number[]> = {};
  try {
    const t = await fetchVitalTrends(phn);
    for (const s of t.series) trends[s.name] = s.points.map((p) => p.value);
  } catch {
    trends = {};
  }

  const latest = summary.results[0] ?? null;
  const signals = {
    overdueVaccines,
    latestResult: latest
      ? { text: latest.text, conclusion: latest.conclusion, critical: latest.critical, ref: latest.ref }
      : null,
    medsCount: summary.medications.length,
    medications: summary.medications.slice(0, 8).map((m) => ({ text: m.text, ref: m.ref })),
    accessRecent: accessLog.slice(0, 5).map(describeAccess),
  };

  return (
    <PatientApp
      concierge={<Concierge patientPhn={phn} name={summary.patient.name} signals={signals} />}
      summary={<SummaryView summary={summary} trends={trends} />}
      record={<RecordView summary={summary} />}
      me={<MeView accessLog={accessLog} />}
      rail={<SnapshotRail summary={summary} trends={trends} />}
    />
  );
}
