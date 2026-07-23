"use client";

/*
 * Face-recognition consent toggle (FR-5.2). The patient turns face check-in on
 * or off; the change writes a FHIR Consent + updates the MPI gate immediately.
 * Plain language, explicit about what it means (07 §12.3).
 */
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@medagent/ui";

export function ConsentToggle() {
  const t = useTranslations("consent");
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch("/api/portal/consent", { cache: "no-store" });
        if (res.ok) setEnabled((await res.json()).face_recognition);
        else setError(true);
      } catch {
        setError(true);
      }
    })();
  }, []);

  async function toggle() {
    if (enabled === null) return;
    setBusy(true);
    setError(false);
    try {
      const res = await fetch("/api/portal/consent", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ face_recognition: !enabled }),
      });
      if (res.ok) setEnabled((await res.json()).face_recognition);
      else setError(true);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground">{t("faceExplain")}</p>
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium">
          {enabled === null ? t("loading") : enabled ? t("on") : t("off")}
        </span>
        <Button
          variant={enabled ? "secondary" : "primary"}
          onClick={() => void toggle()}
          disabled={busy || enabled === null}
        >
          {enabled ? t("turnOff") : t("turnOn")}
        </Button>
      </div>
      {error ? <p role="alert" className="text-sm text-destructive">{t("error")}</p> : null}
      <p className="text-2xs text-muted-foreground">{t("effect")}</p>
    </div>
  );
}
