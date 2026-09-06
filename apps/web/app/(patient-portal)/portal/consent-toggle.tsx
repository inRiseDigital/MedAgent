"use client";

/*
 * Patient consent controls (FR-5.2).
 *
 * Two independent surfaces, each writing a versioned FHIR Consent via the BFF
 * (`/api/portal/consent`), which forwards to core-api with the session token:
 *
 *   1. Face-recognition check-in (biometric gate) — unchanged; plain language,
 *      explicit about what it means (07 §12.3).
 *   2. Per-purpose record sharing — Treatment, Research and Marketing/third-party,
 *      each togglable on its own. Denying Research does not touch Treatment, etc.
 *
 * Theme-token driven (works in the patient .mh theme and the shared theme) and
 * accessible (each control is a labelled `role="switch"`).
 */
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@medagent/ui";

type PurposeId = "treatment" | "research" | "marketing";

type ConsentState = {
  face_recognition: boolean;
  purposes: Record<PurposeId, boolean>;
};

const PURPOSES: { id: PurposeId; label: string; detail: string }[] = [
  {
    id: "treatment",
    label: "Treatment & care",
    detail: "Let clinicians involved in your care see your record.",
  },
  {
    id: "research",
    label: "Research",
    detail: "Allow approved, de-identified use for medical research.",
  },
  {
    id: "marketing",
    label: "Marketing & third parties",
    detail: "Share with third parties for outreach and marketing.",
  },
];

function normalize(data: unknown): ConsentState {
  const d = (data ?? {}) as { face_recognition?: unknown; purposes?: Record<string, unknown> };
  const p = d.purposes ?? {};
  // Default is ALLOW (true): absence of a stored deny never shows as "denied".
  return {
    face_recognition: Boolean(d.face_recognition),
    purposes: {
      treatment: p.treatment !== false,
      research: p.research !== false,
      marketing: p.marketing !== false,
    },
  };
}

function Switch({
  on,
  label,
  disabled,
  onToggle,
}: {
  on: boolean;
  label: string;
  disabled: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={onToggle}
      className="relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50"
      style={{ background: on ? "var(--success, #16a34a)" : "var(--muted, #d1d5db)" }}
    >
      <span
        className="inline-block h-5 w-5 rounded-full shadow transition-transform"
        style={{ background: "var(--card, #ffffff)", transform: on ? "translateX(22px)" : "translateX(2px)" }}
      />
    </button>
  );
}

export function ConsentToggle() {
  const t = useTranslations("consent");
  const [state, setState] = useState<ConsentState | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch("/api/portal/consent", { cache: "no-store" });
        if (res.ok) setState(normalize(await res.json()));
        else setError(true);
      } catch {
        setError(true);
      }
    })();
  }, []);

  async function put(id: string, body: Record<string, unknown>) {
    if (!state || pending) return;
    setPending(id);
    setError(false);
    try {
      const res = await fetch("/api/portal/consent", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) setState(normalize(await res.json()));
      else setError(true);
    } catch {
      setError(true);
    } finally {
      setPending(null);
    }
  }

  const faceEnabled = state?.face_recognition ?? false;

  return (
    <div className="space-y-5">
      {/* Face-recognition check-in (biometric gate) — unchanged surface. */}
      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">{t("faceExplain")}</p>
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium">
            {state === null ? t("loading") : faceEnabled ? t("on") : t("off")}
          </span>
          <Button
            variant={faceEnabled ? "secondary" : "primary"}
            onClick={() => void put("face_recognition", { face_recognition: !faceEnabled })}
            disabled={pending !== null || state === null}
          >
            {faceEnabled ? t("turnOff") : t("turnOn")}
          </Button>
        </div>
        <p className="text-2xs text-muted-foreground">{t("effect")}</p>
      </div>

      {/* Per-purpose record sharing — Treatment / Research / Marketing, independent. */}
      <div className="space-y-2">
        <p className="text-sm font-medium">Who can use your record, and why</p>
        <p className="text-2xs text-muted-foreground">
          Allow or deny each purpose on its own. Every view is logged; you can change this anytime.
        </p>
        <ul className="divide-y divide-border rounded-lg border border-border">
          {PURPOSES.map((purpose) => {
            const granted = state?.purposes[purpose.id] ?? true;
            return (
              <li key={purpose.id} className="flex items-center justify-between gap-3 px-3 py-2.5">
                <span className="flex min-w-0 flex-col">
                  <span className="text-sm font-medium">{purpose.label}</span>
                  <span className="text-2xs text-muted-foreground">{purpose.detail}</span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <span
                    className="text-2xs font-medium"
                    style={{ color: granted ? "var(--success, #16a34a)" : "var(--muted-foreground, #6b7280)" }}
                  >
                    {granted ? t("on") : t("off")}
                  </span>
                  <Switch
                    on={granted}
                    label={purpose.label}
                    disabled={pending !== null || state === null}
                    onToggle={() => void put(purpose.id, { purpose: purpose.id, granted: !granted })}
                  />
                </span>
              </li>
            );
          })}
        </ul>
      </div>

      {error ? <p role="alert" className="text-sm text-destructive">{t("error")}</p> : null}
    </div>
  );
}
