"use client";

/*
 * Prescription proposal + e-sign-off (06 §7, FR-4.3/4.8). Draft a prescription,
 * preview the DETERMINISTIC Rx-safety verdict (pass/warn/block), and sign it off.
 * The engine — not this UI — is the safety authority: a `block` disables commit;
 * a `warn` requires an override reason; core-api re-screens on commit regardless.
 */
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Badge, Button, type BadgeProps } from "@medagent/ui";

interface Finding {
  code: string;
  severity: string;
  rationale: string;
}
interface Verdict {
  verdict: "pass" | "warn" | "block";
  codes: string[];
  findings: Finding[];
  dataset_version?: string;
}

const VARIANT: Record<string, BadgeProps["variant"]> = { pass: "pass", warn: "warn", block: "block" };

export function ProposalPanel({ patientId }: { patientId: string }) {
  const t = useTranslations("proposal");
  const [drug, setDrug] = useState("");
  const [dose, setDose] = useState("");
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setVerdict(null);
    setResult(null);
    setError(null);
    setOverrideReason("");
  };

  async function checkSafety() {
    if (!drug.trim()) return;
    setBusy(true);
    reset();
    try {
      const res = await fetch("/api/proposals/prescreen", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ patient: patientId, drug }),
      });
      if (!res.ok) {
        setError(t("screenError"));
        return;
      }
      setVerdict((await res.json()) as Verdict);
    } catch {
      setError(t("screenError"));
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const res = await fetch("/api/proposals/commit", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          kind: "prescription",
          patient: patientId,
          payload: { drug, dose_text: dose },
          override_reason: overrideReason || undefined,
        }),
      });
      const data = (await res.json()) as {
        committed?: string;
        detail?: { error?: string; verdict?: Verdict } | string;
      };
      if (res.status === 201 && data.committed) {
        setResult(data.committed);
        return;
      }
      if (res.status === 409 && typeof data.detail === "object" && data.detail.verdict) {
        setVerdict(data.detail.verdict);
        setError(t("blocked"));
      } else if (res.status === 422 && typeof data.detail === "object" && data.detail.verdict) {
        setVerdict(data.detail.verdict);
        setError(t("overrideRequired"));
      } else {
        setError(t("commitError"));
      }
    } catch {
      setError(t("commitError"));
    } finally {
      setBusy(false);
    }
  }

  const blocked = verdict?.verdict === "block";
  const needsOverride = verdict?.verdict === "warn";

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{t("intro")}</p>
      <div className="flex flex-wrap gap-2">
        <input
          value={drug}
          onChange={(e) => { setDrug(e.target.value); reset(); }}
          placeholder={t("drug")}
          aria-label={t("drug")}
          className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring"
        />
        <input
          value={dose}
          onChange={(e) => setDose(e.target.value)}
          placeholder={t("dose")}
          aria-label={t("dose")}
          className="w-40 rounded-md border border-border bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring"
        />
        <Button type="button" variant="secondary" onClick={() => void checkSafety()} disabled={busy || !drug.trim()}>
          {t("check")}
        </Button>
      </div>

      {verdict ? (
        <div
          className={
            "rounded-md border p-3 text-sm " +
            (blocked
              ? "border-destructive bg-destructive-surface"
              : needsOverride
                ? "border-warning bg-warning-surface"
                : "border-success bg-success-surface")
          }
        >
          <div className="flex items-center gap-2">
            <Badge variant={VARIANT[verdict.verdict]}>{t(`verdict.${verdict.verdict}`)}</Badge>
            <span className="font-medium">{verdict.codes.join(", ") || t("noIssues")}</span>
          </div>
          {verdict.findings.length > 0 ? (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
              {verdict.findings.map((f, i) => (
                <li key={i}>
                  <span className="font-medium">[{f.severity}] {f.code}</span> — {f.rationale}
                </li>
              ))}
            </ul>
          ) : null}
          {verdict.dataset_version ? (
            <p className="mt-2 text-2xs text-muted-foreground">{t("dataset", { v: verdict.dataset_version })}</p>
          ) : null}
        </div>
      ) : null}

      {needsOverride ? (
        <textarea
          value={overrideReason}
          onChange={(e) => setOverrideReason(e.target.value)}
          placeholder={t("overridePrompt")}
          aria-label={t("overridePrompt")}
          rows={2}
          className="w-full rounded-md border border-warning bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring"
        />
      ) : null}

      <div className="flex items-center gap-3">
        <Button
          type="button"
          onClick={() => void commit()}
          disabled={busy || !drug.trim() || blocked || (needsOverride && !overrideReason.trim())}
        >
          {t("sign")}
        </Button>
        {result ? <span className="text-sm text-success">{t("committed", { ref: result })}</span> : null}
        {error ? <span role="alert" className="text-sm text-destructive">{error}</span> : null}
      </div>
      <p className="text-2xs text-muted-foreground">{t("footnote")}</p>
    </div>
  );
}
