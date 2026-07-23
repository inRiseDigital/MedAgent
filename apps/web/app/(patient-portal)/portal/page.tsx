/*
 * Patient portal home (FR-5.1/5.3/5.8, 07 §5). Shows the signed-in patient THEIR
 * OWN record — problems, medications, allergies, upcoming appointments — plus a
 * plain-language access log ("who looked at my record"). The patient is resolved
 * from the `phn` session claim (02 §8.5); a patient can only ever see their own
 * compartment. Plain-language, low-literacy-first (07 §12.3).
 */
import { getTranslations } from "next-intl/server";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@medagent/ui";

import {
  fetchAccessLog,
  fetchPatientSummary,
  type AccessLogEntry,
  type PatientSummary,
} from "@/lib/api";
import { getSession } from "@/lib/session-store";
import { ConsentToggle } from "./consent-toggle";

export const dynamic = "force-dynamic";

export default async function PortalHomePage() {
  const t = await getTranslations("portal");
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

  return (
    <main className="mx-auto max-w-3xl space-y-4 py-4">
      <div>
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <p className="text-muted-foreground">
          {summary ? t("greetingNamed", { name: summary.patient.name }) : t("greeting")}
        </p>
      </div>

      {!phn ? (
        <Card>
          <CardContent className="py-6">
            <p className="text-muted-foreground">{t("noRecord")}</p>
          </CardContent>
        </Card>
      ) : !summary ? (
        <Card>
          <CardContent className="py-6">
            <p className="text-muted-foreground">{t("loadError")}</p>
          </CardContent>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>{t("problems")}</CardTitle>
            </CardHeader>
            <CardContent>
              {summary.problems.length ? (
                <ul className="space-y-1">
                  {summary.problems.map((p) => (
                    <li key={p.ref} className="text-sm">{p.text}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">{t("none")}</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("medications")}</CardTitle>
            </CardHeader>
            <CardContent>
              {summary.medications.length ? (
                <ul className="space-y-1">
                  {summary.medications.map((m) => (
                    <li key={m.ref} className="text-sm">{m.text}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">{t("none")}</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("allergies")}</CardTitle>
            </CardHeader>
            <CardContent>
              {summary.allergies.length ? (
                <ul className="flex flex-wrap gap-2">
                  {summary.allergies.map((a) => (
                    <li key={a.ref}>
                      <Badge variant={a.criticality === "high" ? "block" : "warn"}>{a.text}</Badge>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">{t("noAllergies")}</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("appointments")}</CardTitle>
            </CardHeader>
            <CardContent>
              {summary.appointments.length ? (
                <ul className="space-y-1">
                  {summary.appointments.map((ap, i) => (
                    <li key={i} className="text-sm tabular-nums">
                      {ap.start ? new Date(ap.start).toLocaleString() : "—"}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">{t("none")}</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("consentTitle")}</CardTitle>
            </CardHeader>
            <CardContent>
              <ConsentToggle />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("accessLog")}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="mb-2 text-sm text-muted-foreground">{t("accessLogIntro")}</p>
              {accessLog.length ? (
                <ul className="divide-y divide-border">
                  {accessLog.map((e, i) => (
                    <li key={i} className="flex items-center justify-between gap-3 py-2 text-sm">
                      <span>{e.type}</span>
                      <span className="text-muted-foreground tabular-nums">
                        {e.recorded ? new Date(e.recorded).toLocaleString() : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">{t("accessLogEmpty")}</p>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </main>
  );
}
