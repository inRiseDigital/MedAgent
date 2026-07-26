"use client";

/*
 * Clinical entry (FR-4.1/4.4/4.5/4.6). A compact, structured way for the doctor
 * to write to the record: a coded diagnosis, a vital, a note, or a lab / imaging
 * order. Each commits through the same safety-gated, audited write-back path as
 * prescriptions (core-api /proposals/commit → FHIR + AuditEvent). Prescriptions
 * keep their dedicated sign-off panel because they carry the Rx-safety verdict.
 */
import { useMemo, useState } from "react";
import { ClipboardList, FlaskConical, HeartPulse, Scan, StickyNote } from "lucide-react";
import { Button } from "@medagent/ui";

type Kind = "diagnosis" | "vitals" | "note" | "lab_order" | "imaging_order";

const TABS: { kind: Kind; label: string; Icon: typeof HeartPulse }[] = [
  { kind: "diagnosis", label: "Diagnosis", Icon: ClipboardList },
  { kind: "vitals", label: "Vital", Icon: HeartPulse },
  { kind: "note", label: "Note", Icon: StickyNote },
  { kind: "lab_order", label: "Lab order", Icon: FlaskConical },
  { kind: "imaging_order", label: "Imaging", Icon: Scan },
];

const inputCls =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function ClinicalEntry({ patientId }: { patientId: string }) {
  const [kind, setKind] = useState<Kind>("diagnosis");
  const [f, setF] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const set = (k: string, v: string) => setF((s) => ({ ...s, [k]: v }));
  const reset = () => {
    setF({});
    setResult(null);
    setError(null);
  };

  const canSave = useMemo(() => {
    if (kind === "vitals") return !!f.code_text?.trim() && !!f.value?.trim();
    return !!f.text?.trim();
  }, [kind, f]);

  function payload(): Record<string, unknown> {
    switch (kind) {
      case "diagnosis":
        return { text: f.text, icd10: f.icd10 || undefined, clinical_status: "active" };
      case "vitals":
        return { code_text: f.code_text, value: Number(f.value), unit: f.unit || "", loinc: f.loinc || undefined };
      case "note":
        return { text: f.text, type_text: "Progress note" };
      case "lab_order":
        return { text: f.text, loinc: f.loinc || undefined, priority: "routine" };
      case "imaging_order":
        return { text: f.text, priority: "routine" };
    }
  }

  async function save() {
    if (!canSave || busy) return;
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const res = await fetch("/api/proposals/commit", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ kind, patient: patientId, payload: payload() }),
      });
      const data = (await res.json()) as { committed?: string; detail?: unknown };
      if (res.status === 201 && data.committed) {
        setResult(data.committed);
        setF({});
      } else {
        setError("Could not save. Please check the fields and retry.");
      }
    } catch {
      setError("Could not reach the server. Please retry.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Add a structured entry to the record — written as FHIR and audited on save.
      </p>

      <div className="flex flex-wrap gap-1.5">
        {TABS.map(({ kind: k, label, Icon }) => (
          <button
            key={k}
            type="button"
            onClick={() => {
              setKind(k);
              reset();
            }}
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
              kind === k
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {kind === "diagnosis" && (
          <>
            <input className={inputCls} placeholder="Diagnosis (e.g. Type 2 diabetes mellitus)" value={f.text ?? ""} onChange={(e) => set("text", e.target.value)} />
            <input className={inputCls} placeholder="ICD-10 code (optional, e.g. E11)" value={f.icd10 ?? ""} onChange={(e) => set("icd10", e.target.value)} />
          </>
        )}
        {kind === "vitals" && (
          <>
            <input className={inputCls} placeholder="Vital (e.g. Body weight, Systolic BP)" value={f.code_text ?? ""} onChange={(e) => set("code_text", e.target.value)} />
            <div className="flex gap-2">
              <input className={inputCls} type="number" placeholder="Value" value={f.value ?? ""} onChange={(e) => set("value", e.target.value)} />
              <input className={`${inputCls} w-24`} placeholder="Unit" value={f.unit ?? ""} onChange={(e) => set("unit", e.target.value)} />
            </div>
            <input className={inputCls} placeholder="LOINC code (optional, e.g. 29463-7)" value={f.loinc ?? ""} onChange={(e) => set("loinc", e.target.value)} />
          </>
        )}
        {kind === "note" && (
          <textarea className={`${inputCls} sm:col-span-2`} rows={3} placeholder="Clinical note / consultation findings…" value={f.text ?? ""} onChange={(e) => set("text", e.target.value)} />
        )}
        {kind === "lab_order" && (
          <>
            <input className={inputCls} placeholder="Test (e.g. HbA1c, Full blood count)" value={f.text ?? ""} onChange={(e) => set("text", e.target.value)} />
            <input className={inputCls} placeholder="LOINC code (optional, e.g. 4548-4)" value={f.loinc ?? ""} onChange={(e) => set("loinc", e.target.value)} />
          </>
        )}
        {kind === "imaging_order" && (
          <input className={`${inputCls} sm:col-span-2`} placeholder="Study (e.g. Chest X-ray, CT abdomen)" value={f.text ?? ""} onChange={(e) => set("text", e.target.value)} />
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" onClick={() => void save()} disabled={!canSave || busy}>
          {busy ? "Saving…" : "Save to record"}
        </Button>
        {result ? <span className="text-sm font-medium text-success">Saved · {result}</span> : null}
        {error ? <span role="alert" className="text-sm text-destructive">{error}</span> : null}
      </div>
    </div>
  );
}
