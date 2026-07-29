/*
 * National ops dashboard (FR-12). A read-only command view over the platform's
 * live data: KPI tiles, notifiable-disease outbreak early-warning (colour-coded
 * by signal), and facility capacity (waitlist / free slots / open referrals).
 * Server component; all aggregation is deterministic in core-api. Theme-aware.
 */
import { getTranslations } from "next-intl/server";
import { Activity, AlertTriangle, CalendarClock, FlaskConical, Scan, Send, ShieldAlert, Syringe, Users } from "lucide-react";
import { Card, CardContent } from "@medagent/ui";

import { CLINICAL, requireRoles } from "@/lib/require-role";

import {
  fetchAnalyticsOverview,
  fetchCapacity,
  fetchOutbreak,
  type AnalyticsOverview,
  type CapacityView,
  type OutbreakView,
} from "@/lib/api";

function Kpi({ label, value, Icon }: { label: string; value: number | string; Icon: React.ComponentType<{ className?: string }> }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="text-2xl font-semibold leading-none tabular-nums">{value}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">{label}</p>
        </div>
      </CardContent>
    </Card>
  );
}

const SIGNAL_STYLE: Record<string, string> = {
  alert: "border-destructive/40 bg-destructive-surface text-destructive",
  watch: "border-warning/40 bg-warning-surface text-warning",
  none: "border-border bg-muted/30 text-muted-foreground",
};

export default async function DashboardPage() {
  await requireRoles(CLINICAL); // clinicians only — receptionist bounced to /queue
  const t = await getTranslations("nav");

  let overview: AnalyticsOverview | null = null;
  let outbreak: OutbreakView | null = null;
  let capacity: CapacityView | null = null;
  try {
    [overview, outbreak, capacity] = await Promise.all([
      fetchAnalyticsOverview(),
      fetchOutbreak(),
      fetchCapacity(),
    ]);
  } catch {
    // best-effort; render whatever resolved
  }

  return (
    <div className="mx-auto max-w-[1200px] space-y-6">
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
          <Activity className="h-4 w-4" />
        </span>
        <h1 className="text-lg font-semibold">{t("dashboard")}</h1>
        {overview ? (
          <span className="ml-auto text-xs text-muted-foreground tabular-nums">
            as of {new Date(overview.as_of).toLocaleString()}
          </span>
        ) : null}
      </div>

      {!overview ? (
        <Card><CardContent className="p-6 text-sm text-muted-foreground">Analytics unavailable.</CardContent></Card>
      ) : (
        <>
          {/* KPI tiles */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            <Kpi label="Patients registered" value={overview.patients_registered} Icon={Users} />
            <Kpi label="Lab reports" value={overview.lab_reports} Icon={FlaskConical} />
            <Kpi label="Imaging studies" value={overview.imaging_studies} Icon={Scan} />
            <Kpi label="Immunizations" value={overview.immunizations} Icon={Syringe} />
            <Kpi label="Open referrals" value={overview.referrals_open} Icon={Send} />
            <Kpi label="Appointments" value={overview.appointments} Icon={CalendarClock} />
            <Kpi label="Notifiable cases" value={overview.notifiable_cases} Icon={ShieldAlert} />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            {/* Outbreak early-warning */}
            <Card>
              <div className="flex items-center gap-2 border-b border-border px-4 py-3">
                <AlertTriangle className="h-4 w-4 text-warning" />
                <h2 className="text-sm font-semibold">Notifiable-disease early-warning</h2>
                {outbreak?.any_alert ? (
                  <span className="ml-auto rounded-md border border-destructive/40 bg-destructive-surface px-2 py-0.5 text-xs font-semibold text-destructive">
                    ALERT
                  </span>
                ) : null}
              </div>
              <CardContent className="p-3">
                {outbreak && outbreak.signals.length > 0 ? (
                  <ul className="space-y-1.5">
                    {outbreak.signals.map((s) => (
                      <li
                        key={s.disease}
                        className={`flex items-center gap-3 rounded-md border px-3 py-2 text-sm ${SIGNAL_STYLE[s.signal] ?? SIGNAL_STYLE.none}`}
                      >
                        <span className="font-medium capitalize">{s.disease.replace(/_/g, " ")}</span>
                        <span className="ml-auto tabular-nums">{s.cases} cases</span>
                        <span className="w-14 text-right text-xs font-semibold uppercase">{s.signal}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="p-3 text-sm text-muted-foreground">No notifiable cases recorded.</p>
                )}
              </CardContent>
            </Card>

            {/* Capacity */}
            <Card>
              <div className="flex items-center gap-2 border-b border-border px-4 py-3">
                <CalendarClock className="h-4 w-4 text-primary" />
                <h2 className="text-sm font-semibold">Facility capacity</h2>
              </div>
              <CardContent className="p-0">
                {capacity && capacity.by_facility.length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-muted-foreground">
                          <th className="px-4 py-2 font-medium">Facility</th>
                          <th className="px-3 py-2 text-right font-medium">Waitlist</th>
                          <th className="px-3 py-2 text-right font-medium">Free slots</th>
                          <th className="px-4 py-2 text-right font-medium">Open referrals</th>
                        </tr>
                      </thead>
                      <tbody>
                        {capacity.by_facility.map((r) => (
                          <tr key={r.facility} className="border-b border-border/50 last:border-0">
                            <td className="px-4 py-2">{r.facility}</td>
                            <td className="px-3 py-2 text-right tabular-nums">{r.waitlist}</td>
                            <td className="px-3 py-2 text-right tabular-nums">{r.free_slots}</td>
                            <td className="px-4 py-2 text-right tabular-nums">{r.open_referrals}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="p-4 text-sm text-muted-foreground">No scheduling or referral activity.</p>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
