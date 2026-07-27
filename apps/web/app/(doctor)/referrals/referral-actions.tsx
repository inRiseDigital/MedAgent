"use client";
/*
 * Referral action buttons (FR-9.3). Posts accept/reject/start/complete to the BFF,
 * then refreshes the server component so the worklist reflects the new state.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@medagent/ui";

const ACTIONS: Record<string, { label: string; next: string[] }> = {
  accept: { label: "Accept", next: ["requested"] },
  reject: { label: "Reject", next: ["requested", "accepted"] },
  start: { label: "Start", next: ["accepted"] },
  complete: { label: "Complete", next: ["accepted", "in-progress"] },
};

export function ReferralActions({ taskId, status }: { taskId: string; status?: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const available = Object.entries(ACTIONS).filter(([, cfg]) => cfg.next.includes(status ?? ""));
  if (available.length === 0) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }

  async function act(action: string) {
    setBusy(action);
    setErr(null);
    try {
      const res = await fetch(`/api/referrals/${encodeURIComponent(taskId)}/act`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action }),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setErr(j.detail ?? `Failed (${res.status})`);
      } else {
        router.refresh();
      }
    } catch {
      setErr("Network error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {available.map(([action, cfg]) => (
        <Button
          key={action}
          size="sm"
          variant={action === "reject" ? "secondary" : "primary"}
          disabled={busy !== null}
          onClick={() => act(action)}
        >
          {busy === action ? "…" : cfg.label}
        </Button>
      ))}
      {err ? <span className="text-xs text-destructive">{err}</span> : null}
    </div>
  );
}
