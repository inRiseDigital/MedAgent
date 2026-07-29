/*
 * Referral inbox (FR-9.2) — the receiving facility's worklist. Reads the inbox
 * for a facility (query param, default the teaching hospital) and lets staff
 * accept / reject / start / complete each referral. Server component; actions go
 * through the BFF. Theme-aware.
 */
import Link from "next/link";
import { Send, ShieldAlert } from "lucide-react";
import { Badge, Card, CardContent } from "@medagent/ui";

import { fetchReferralInbox, type ReferralInbox } from "@/lib/api";
import { CLINICAL, requireRoles } from "@/lib/require-role";
import { ReferralActions } from "./referral-actions";

const DEFAULT_FACILITY = "teaching-hospital";
const FACILITIES = [DEFAULT_FACILITY, "moh-epi-unit", "base-hospital", "district-derm"];

const PRIORITY_BADGE: Record<string, "block" | "warn" | "neutral"> = {
  stat: "block",
  asap: "block",
  urgent: "warn",
  routine: "neutral",
};

export default async function ReferralsPage({
  searchParams,
}: {
  searchParams: Promise<{ facility?: string; closed?: string }>;
}) {
  await requireRoles(CLINICAL); // clinicians only
  const { facility: facParam, closed } = await searchParams;
  const facility = facParam ?? DEFAULT_FACILITY;
  const includeClosed = closed === "1";

  let inbox: ReferralInbox | null = null;
  try {
    inbox = await fetchReferralInbox(facility, includeClosed);
  } catch {
    inbox = null;
  }

  return (
    <div className="mx-auto max-w-[1100px] space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
          <Send className="h-4 w-4" />
        </span>
        <h1 className="text-lg font-semibold">Referral inbox</h1>
        <div className="ml-auto flex flex-wrap gap-1.5">
          {FACILITIES.map((f) => (
            <Link
              key={f}
              href={`/referrals?facility=${encodeURIComponent(f)}${includeClosed ? "&closed=1" : ""}`}
              className={`rounded-md border px-2.5 py-1 text-xs ${
                f === facility
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:bg-muted/50"
              }`}
            >
              {f}
            </Link>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <span>
          {inbox ? `${inbox.count} ${includeClosed ? "total" : "active"}` : "unavailable"} · {facility}
        </span>
        <Link
          href={`/referrals?facility=${encodeURIComponent(facility)}${includeClosed ? "" : "&closed=1"}`}
          className="underline underline-offset-2 hover:text-foreground"
        >
          {includeClosed ? "Show active only" : "Include closed"}
        </Link>
      </div>

      {!inbox ? (
        <Card><CardContent className="p-6 text-sm text-muted-foreground">Inbox unavailable.</CardContent></Card>
      ) : inbox.items.length === 0 ? (
        <Card><CardContent className="p-6 text-sm text-muted-foreground">No referrals for this facility.</CardContent></Card>
      ) : (
        <div className="space-y-2">
          {inbox.items.map((r) => (
            <Card key={r.task_id}>
              <CardContent className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{r.specialty ?? "Referral"}</span>
                    <Badge variant={PRIORITY_BADGE[r.priority ?? "routine"] ?? "neutral"}>
                      {r.priority ?? "routine"}
                    </Badge>
                    {r.reason?.toLowerCase().includes("urgent imaging") ? (
                      <ShieldAlert className="h-3.5 w-3.5 text-destructive" aria-label="urgent imaging" />
                    ) : null}
                    <span className="rounded bg-muted/50 px-1.5 py-0.5 text-[0.7rem] uppercase tracking-wide text-muted-foreground">
                      {r.status}
                    </span>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-muted-foreground">
                    {r.patient_name ?? r.patient_ref ?? "?"} · {r.reason ?? "—"}
                    {r.requested_by ? ` · by ${r.requested_by.slice(0, 8)}` : ""}
                  </p>
                </div>
                <ReferralActions taskId={r.task_id} status={r.status} />
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
