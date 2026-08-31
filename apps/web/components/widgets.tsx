/*
 * Generative-UI widget registry (P1). The agent streams `data-widget` frames
 * ({id, kind, title, data, state?, actions?}); this maps `kind` → a React
 * component so rich widgets render inline in the chat, in both the patient
 * concierge (.mh theme) and the doctor copilot. Styled with the shared semantic
 * tokens so it adapts to either theme.
 */
"use client";

import {
  AlertTriangle,
  Activity,
  CheckCircle2,
  ChevronRight,
  Info,
  Loader2,
  Sparkles,
} from "lucide-react";
import { type ReactNode, useState } from "react";

import { LineFade } from "@/components/charts";

export interface WidgetSpec {
  id: string;
  kind: string;
  title?: string;
  data: Record<string, unknown>;
  state?: "idle" | "pending" | "confirmed" | "done" | string;
  actions?: { id: string; label: string; kind?: string }[];
}

/** Pull a trailing/inline `[source: Type/id]` out of an item string. */
function splitSource(s: string): { text: string; ref?: string } {
  const m = s.match(/\[source:\s*([A-Za-z]+\/[A-Za-z0-9._-]+)\]/);
  if (!m) return { text: s.trim() };
  return { text: s.replace(m[0], "").trim().replace(/\s+·?\s*$/, ""), ref: m[1] };
}

function num(v: unknown): number {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}

// ---- shell -----------------------------------------------------------------
function Shell({ tone = "default", icon, title, children }: {
  tone?: "default" | "block" | "warn" | "good" | "info";
  icon?: ReactNode; title?: string; children: ReactNode;
}) {
  const accent =
    tone === "block" ? "var(--destructive)" :
    tone === "warn" ? "var(--warning)" :
    tone === "good" ? "var(--success)" :
    "var(--primary)";
  return (
    <div className="w-full max-w-[94%] rounded-2xl border bg-[var(--card)] text-[var(--card-foreground)]"
      style={{ borderColor: "var(--border)", boxShadow: "var(--mh-shadow, 0 1px 2px rgba(0,0,0,.06))" }}>
      <div className="h-1 rounded-t-2xl" style={{ background: accent }} />
      <div className="p-3.5">
        {title ? (
          <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold">
            <span style={{ color: accent }}>{icon}</span>
            <span>{title}</span>
          </div>
        ) : null}
        {children}
      </div>
    </div>
  );
}

function RefChip({ refId }: { refId: string }) {
  const type = refId.split("/")[0];
  return (
    <span className="ml-1 inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium font-mono tracking-tight"
      style={{ background: "var(--muted)", color: "var(--muted-foreground)" }}>{type}</span>
  );
}

// ---- widgets ---------------------------------------------------------------
function SafetyAlert({ spec }: { spec: WidgetSpec }) {
  const severity = String(spec.data.severity ?? "warn");
  const items = Array.isArray(spec.data.items) ? (spec.data.items as string[]) : [];
  const tone = severity === "block" ? "block" : severity === "info" ? "info" : "warn";
  return (
    <Shell tone={tone} icon={<AlertTriangle className="h-4 w-4" />} title={spec.title ?? "Safety flags"}>
      <ul className="flex flex-col gap-1.5">
        {items.map((raw, i) => {
          const { text, ref } = splitSource(raw);
          return (
            <li key={i} className="flex items-start gap-2 text-[13px] leading-snug">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ background: tone === "block" ? "var(--destructive)" : "var(--warning)" }} />
              <span>{text}{ref ? <RefChip refId={ref} /> : null}</span>
            </li>
          );
        })}
      </ul>
    </Shell>
  );
}

function RecordLinks({ spec, onAction }: { spec: WidgetSpec; onAction?: (id: string) => void }) {
  const items = Array.isArray(spec.data.items) ? (spec.data.items as { label: string; ref: string }[]) : [];
  return (
    <Shell icon={<Sparkles className="h-4 w-4" />} title={spec.title ?? "In your record"}>
      <div className="flex flex-col gap-1">
        {items.map((it, i) => (
          <button key={i} type="button" onClick={() => onAction?.(it.ref)}
            className="group flex items-center justify-between rounded-lg px-2 py-1.5 text-left text-[13px] transition-colors hover:bg-[var(--muted)]">
            <span className="flex items-center gap-2">
              <span>{it.label}</span><RefChip refId={it.ref} />
            </span>
            <ChevronRight className="h-3.5 w-3.5 opacity-40 group-hover:opacity-80" />
          </button>
        ))}
      </div>
    </Shell>
  );
}

function MetricTrend({ spec }: { spec: WidgetSpec }) {
  const label = String(spec.data.label ?? spec.title ?? "Trend");
  const unit = String(spec.data.unit ?? "");
  const points = Array.isArray(spec.data.points) ? (spec.data.points as { t?: string; v?: unknown }[]) : [];
  const series = points.map((p) => num(p.v));
  const latest = series.length ? series[series.length - 1] : null;
  return (
    <Shell icon={<Activity className="h-4 w-4" />} title={label}>
      <div className="flex items-end justify-between gap-3">
        <div className="text-2xl font-semibold tabular-nums">
          {latest ?? "—"}<span className="ml-1 text-xs font-normal opacity-60">{unit}</span>
        </div>
        <div className="min-w-[120px] flex-1">
          {series.length >= 2 ? <LineFade data={series} gradientId={`grad-${spec.id}`} /> : <span className="text-xs opacity-50">not enough points</span>}
        </div>
      </div>
    </Shell>
  );
}

function StatGrid({ spec }: { spec: WidgetSpec }) {
  const stats = Array.isArray(spec.data.stats) ? (spec.data.stats as { label: string; value: string; tone?: string }[]) : [];
  const col = (t?: string) => t === "warn" ? "var(--warning)" : t === "block" ? "var(--destructive)" : t === "good" ? "var(--success)" : "var(--foreground)";
  return (
    <Shell icon={<Info className="h-4 w-4" />} title={spec.title}>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {stats.map((s, i) => (
          <div key={i} className="rounded-xl px-2.5 py-2" style={{ background: "var(--muted)" }}>
            <div className="text-[11px] opacity-60">{s.label}</div>
            <div className="text-base font-semibold tabular-nums" style={{ color: col(s.tone) }}>{s.value}</div>
          </div>
        ))}
      </div>
    </Shell>
  );
}

function NextBestAction({ spec, onAction }: { spec: WidgetSpec; onAction?: (id: string) => void }) {
  const actions = Array.isArray(spec.data.actions) ? (spec.data.actions as { id: string; label: string }[]) : [];
  return (
    <div className="flex flex-wrap gap-1.5">
      {actions.map((a) => (
        <button key={a.id} type="button" onClick={() => onAction?.(a.id)}
          className="inline-flex items-center gap-1 rounded-full border px-3 py-1.5 text-[13px] font-medium transition-colors hover:bg-[var(--muted)]"
          style={{ borderColor: "var(--border-strong, var(--border))" }}>
          {a.label}
        </button>
      ))}
    </div>
  );
}

function TimelineW({ spec }: { spec: WidgetSpec }) {
  const events = Array.isArray(spec.data.events) ? (spec.data.events as { t?: string; label: string; ref?: string }[]) : [];
  return (
    <Shell title={spec.title ?? "Timeline"}>
      <ol className="relative ml-1 flex flex-col gap-2 border-l pl-3.5" style={{ borderColor: "var(--border)" }}>
        {events.map((e, i) => (
          <li key={i} className="relative text-[13px]">
            <span className="absolute -left-[18px] top-1 h-2 w-2 rounded-full" style={{ background: "var(--primary)" }} />
            {e.t ? <span className="mr-2 text-[11px] opacity-55 tabular-nums">{e.t}</span> : null}
            <span>{e.label}{e.ref ? <RefChip refId={e.ref} /> : null}</span>
          </li>
        ))}
      </ol>
    </Shell>
  );
}

function SummaryWidget({ spec }: { spec: WidgetSpec }) {
  const tone = String(spec.data.tone ?? "info");
  const points = Array.isArray(spec.data.points) ? (spec.data.points as string[]) : [];
  const t = tone === "urgent" ? "block" : tone === "warn" ? "warn" : tone === "good" ? "good" : "info";
  return (
    <Shell tone={t} icon={<CheckCircle2 className="h-4 w-4" />} title={spec.title}>
      <ul className="flex flex-col gap-1">
        {points.map((p, i) => {
          const { text, ref } = splitSource(p);
          return <li key={i} className="flex gap-2 text-[13px]"><span className="opacity-50">•</span><span>{text}{ref ? <RefChip refId={ref} /> : null}</span></li>;
        })}
      </ul>
    </Shell>
  );
}

function ConfirmAction({ spec, onConfirm }: WidgetProps) {
  const [state, setState] = useState<"pending" | "submitting" | "done" | "error">("pending");
  const action = String(spec.data.action ?? "");
  const params = (spec.data.params as Record<string, unknown>) ?? {};
  const prompt = String(spec.data.prompt ?? "Confirm this action?");
  const confirmLabel = String(spec.data.confirmLabel ?? "Confirm");
  const doneLabel = String(spec.data.doneLabel ?? "Done");
  if (state === "done") {
    return (
      <Shell tone="good" icon={<CheckCircle2 className="h-4 w-4" />} title={spec.title ?? "Confirmed"}>
        <p className="text-[13px]">{doneLabel} ✓</p>
      </Shell>
    );
  }
  return (
    <Shell tone="info" icon={<CheckCircle2 className="h-4 w-4" />} title={spec.title ?? "Confirm"}>
      <p className="mb-2 text-[13px] leading-snug">{prompt}</p>
      <div className="flex items-center gap-2">
        <button type="button" disabled={state === "submitting"}
          className="inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[13px] font-semibold text-[var(--primary-foreground)] disabled:opacity-60"
          style={{ background: "var(--primary)" }}
          onClick={async () => {
            setState("submitting");
            const ok = onConfirm ? await onConfirm(action, params) : false;
            setState(ok ? "done" : "error");
          }}>
          {state === "submitting" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          {confirmLabel}
        </button>
        {state !== "submitting" ? (
          <button type="button" onClick={() => setState("done")}
            className="rounded-full px-3 py-1.5 text-[13px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]">Not now</button>
        ) : null}
        {state === "error" ? <span className="text-[12px]" style={{ color: "var(--destructive)" }}>Couldn&apos;t complete — try again.</span> : null}
      </div>
    </Shell>
  );
}

interface WidgetProps {
  spec: WidgetSpec;
  onAction?: (id: string) => void;
  onConfirm?: (action: string, params: Record<string, unknown>) => Promise<boolean>;
}

const REGISTRY: Record<string, (p: WidgetProps) => ReactNode> = {
  "safety-alert": SafetyAlert,
  "record-links": RecordLinks,
  "metric-trend": MetricTrend,
  "stat-grid": StatGrid,
  "next-best-action": NextBestAction,
  "confirm-action": ConfirmAction,
  timeline: TimelineW,
  summary: SummaryWidget,
};

/** Render one widget spec from the registry. Unknown kinds render nothing. */
export function Widget({ spec, onAction, onConfirm }: WidgetProps) {
  const Comp = REGISTRY[spec.kind];
  if (!Comp) return null;
  return <>{Comp({ spec, onAction, onConfirm })}</>;
}

export const WIDGET_KINDS = Object.keys(REGISTRY);
