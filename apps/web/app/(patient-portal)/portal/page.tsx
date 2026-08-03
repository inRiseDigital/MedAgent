/*
 * Patient portal home (FR-5, 07 §5) — now a chat-first app: the Concierge is the
 * default tab, with Health / Record / Me alongside. The patient is resolved from
 * the `phn` session claim (02 §8.5) and only ever sees their own compartment.
 * Data is fetched server-side and handed to the client shell.
 */
import {
  fetchAccessLog,
  fetchPatientSummary,
  type AccessLogEntry,
  type PatientSummary,
} from "@/lib/api";
import { getSession } from "@/lib/session-store";
import { Concierge } from "./concierge";
import { PatientApp } from "./patient-app";
import { HealthView, MeView, RecordView } from "./views";

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
      <div className="rounded-2xl border border-border bg-card p-6 text-center text-muted-foreground">
        {!phn
          ? "No linked patient record for this account."
          : "We couldn't load your record right now. Please try again shortly."}
      </div>
    );
  }

  return (
    <PatientApp
      concierge={<Concierge patientPhn={phn} name={summary.patient.name} />}
      health={<HealthView summary={summary} />}
      record={<RecordView summary={summary} />}
      me={<MeView accessLog={accessLog} />}
    />
  );
}
