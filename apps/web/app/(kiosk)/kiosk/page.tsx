"use client";

/*
 * Kiosk check-in screen — S1 scaffold, implemented in S2 per
 * docs/solution/11. Target design (05 §3/§5, 06 §1):
 * - Driven by the notify-service SSE match feed (device service-account
 *   session; @/lib/sse ticket handoff).
 * - RECOGNISED (consent granted, confidence ≥ threshold): patient is
 *   queued; kiosk confirms check-in. Confidence is shown as bands, never
 *   raw percentages (05 §5).
 * - NOT RECOGNISED / below threshold / liveness-degraded: warm hand-off
 *   to reception — a manual-verification task appears in the reception
 *   view; the kiosk never says "rejected". Opt-outs are dropped silently
 *   upstream and simply check in at the desk (01 §4.1).
 * - Idle state scans between patients.
 * The demo state switcher below exists only so the scaffold's states are
 * reviewable before the SSE feed lands; it is removed in S2.
 */
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Badge, Button, Card, CardContent, Spinner } from "@medagent/ui";

type KioskState = "idle" | "recognised" | "notRecognised";

export default function KioskCheckinPage() {
  const t = useTranslations("kiosk");
  const [state, setState] = useState<KioskState>("idle");

  return (
    <main className="w-full max-w-xl space-y-6 text-center">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <p className="text-lg text-muted-foreground">{t("subtitle")}</p>

      <Card>
        <CardContent className="space-y-4 p-8">
          {state === "idle" ? (
            <div className="flex flex-col items-center gap-3">
              <Spinner label={t("idleBody")} />
              <p className="text-muted-foreground">{t("idleBody")}</p>
            </div>
          ) : null}

          {state === "recognised" ? (
            <div className="flex flex-col items-center gap-3">
              <Badge variant="pass">{t("recognised.title")}</Badge>
              <p className="text-lg font-medium">{t("recognised.body")}</p>
              <p className="text-muted-foreground">{t("recognised.queueNote")}</p>
            </div>
          ) : null}

          {state === "notRecognised" ? (
            <div className="flex flex-col items-center gap-3">
              <Badge variant="warn">{t("notRecognised.title")}</Badge>
              <p className="text-lg font-medium">{t("notRecognised.body")}</p>
              <p className="text-muted-foreground">{t("notRecognised.assistNote")}</p>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* S1-only preview controls — removed when the SSE feed lands (S2). */}
      <fieldset className="flex items-center justify-center gap-2">
        <legend className="mb-2 text-xs text-muted-foreground">{t("demo.label")}</legend>
        <Button size="sm" variant="secondary" onClick={() => setState("idle")}>
          {t("demo.idle")}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => setState("recognised")}>
          {t("demo.recognised")}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => setState("notRecognised")}>
          {t("demo.notRecognised")}
        </Button>
      </fieldset>
    </main>
  );
}
