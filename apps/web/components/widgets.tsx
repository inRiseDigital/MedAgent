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
  Bell,
  CalendarClock,
  Check,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Eye,
  FlaskConical,
  Info,
  ListChecks,
  Loader2,
  PackageCheck,
  Pill,
  ReceiptText,
  ShieldCheck,
  Sparkles,
  Stethoscope,
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

// "Who has seen your record" — a calm, trustworthy access ledger.
function AccessLog({ spec }: { spec: WidgetSpec }) {
  const items = Array.isArray(spec.data.items)
    ? (spec.data.items as { who: string; when: string; kind?: string; you?: boolean }[])
    : [];
  return (
    <Shell icon={<Eye className="h-4 w-4" />} title={spec.title ?? "Who has seen your record"}>
      <ul className="flex flex-col gap-1.5">
        {items.map((it, i) => (
          <li key={i} className="flex items-center gap-2 text-[13px] leading-snug">
            <ShieldCheck className="h-3.5 w-3.5 shrink-0" style={{ color: "var(--muted-foreground)" }} />
            <span className="font-semibold">{it.who}</span>
            {it.you ? (
              <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                style={{ background: "var(--muted)", color: "var(--success)" }}>you</span>
            ) : null}
            {it.kind ? <RefChip refId={it.kind} /> : null}
            <span className="ml-auto shrink-0 text-[11px] tabular-nums" style={{ color: "var(--muted-foreground)" }}>{it.when}</span>
          </li>
        ))}
      </ul>
    </Shell>
  );
}

// "Who can access your record" — tap a scope to grant/revoke (parent wires the route).
function ConsentPanel({ spec, onAction }: WidgetProps) {
  const scopes = Array.isArray(spec.data.scopes)
    ? (spec.data.scopes as { id: string; label: string; granted: boolean; detail?: string }[])
    : [];
  return (
    <Shell tone="good" icon={<ShieldCheck className="h-4 w-4" />} title={spec.title ?? "Who can access your record"}>
      <div className="flex flex-col gap-0.5">
        {scopes.map((s) => (
          <button key={s.id} type="button" aria-pressed={s.granted} onClick={() => onAction?.(s.id)}
            className="group flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-[var(--muted)]">
            <span className="flex min-w-0 flex-col">
              <span className="text-[13px] font-medium">{s.label}</span>
              {s.detail ? <span className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>{s.detail}</span> : null}
            </span>
            <span className="flex shrink-0 items-center gap-1.5">
              <span className="text-[11px] font-medium" style={{ color: s.granted ? "var(--success)" : "var(--muted-foreground)" }}>
                {s.granted ? "Granted" : "Revoked"}
              </span>
              <span className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors"
                style={{ background: s.granted ? "var(--success)" : "var(--muted)" }}>
                <span className="h-4 w-4 rounded-full transition-transform"
                  style={{ background: "var(--card)", transform: s.granted ? "translateX(18px)" : "translateX(2px)" }} />
              </span>
            </span>
          </button>
        ))}
      </div>
      <p className="mt-2 text-[11px]" style={{ color: "var(--muted-foreground)" }}>
        Every view is logged; you can change this anytime.
      </p>
    </Shell>
  );
}

// The doctor consult session — the agent streams a grounded agenda; the doctor
// confirms each item (a real tap) before it counts, then completes the visit.
type ConsultItem = { id: string; type: string; label: string; detail?: string; ref?: string };

const CONSULT_ICON: Record<string, typeof Activity> = {
  reason: Stethoscope,
  problem: Activity,
  medication: Pill,
  result: FlaskConical,
  overdue: Bell,
  followup: CalendarClock,
};

function ConsultSession({ spec, onConfirm }: WidgetProps) {
  const items = Array.isArray(spec.data.items) ? (spec.data.items as ConsultItem[]) : [];
  const [confirmed, setConfirmed] = useState<Set<string>>(() => new Set());
  const [state, setState] = useState<"active" | "submitting" | "done">("active");

  const toggle = (id: string) =>
    setConfirmed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const count = confirmed.size;
  const total = items.length;

  if (state === "done") {
    return (
      <Shell tone="good" icon={<CheckCircle2 className="h-4 w-4" />} title={spec.title ?? "Consultation"}>
        <p className="text-[13px]">Consultation summarised ✓</p>
      </Shell>
    );
  }

  return (
    <Shell tone="info" icon={<ClipboardList className="h-4 w-4" />} title={spec.title ?? "Consultation"}>
      <ul className="flex flex-col gap-0.5">
        {items.map((it) => {
          const on = confirmed.has(it.id);
          const Icon = CONSULT_ICON[it.type] ?? Info;
          return (
            <li key={it.id}>
              <button type="button" aria-pressed={on} onClick={() => toggle(it.id)}
                className="group flex w-full items-start gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-[var(--muted)]">
                <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-[5px] border transition-colors"
                  style={{ borderColor: on ? "var(--success)" : "var(--border)", background: on ? "var(--success)" : "transparent" }}>
                  {on ? <Check className="h-3 w-3" style={{ color: "var(--card)" }} /> : null}
                </span>
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="flex flex-wrap items-center gap-1.5">
                    <Icon className="h-3.5 w-3.5 shrink-0" style={{ color: "var(--muted-foreground)" }} />
                    <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium font-mono tracking-tight"
                      style={{ background: "var(--muted)", color: "var(--muted-foreground)" }}>{it.type}</span>
                    <span className="text-[13px] leading-snug"
                      style={on ? { textDecoration: "line-through", color: "var(--muted-foreground)" } : undefined}>{it.label}</span>
                    {it.ref ? <RefChip refId={it.ref} /> : null}
                  </span>
                  {it.detail ? <span className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>{it.detail}</span> : null}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <div className="mt-3 flex items-center justify-between gap-3 border-t pt-3" style={{ borderColor: "var(--border)" }}>
        <span className="text-[12px] tabular-nums" style={{ color: "var(--muted-foreground)" }}>{count} of {total} confirmed</span>
        <button type="button" disabled={count < 1 || state === "submitting"}
          className="inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[13px] font-semibold text-[var(--primary-foreground)] disabled:opacity-50"
          style={{ background: "var(--primary)" }}
          onClick={async () => {
            setState("submitting");
            const ok = onConfirm ? await onConfirm("consult-complete", { confirmed: [...confirmed], count }) : false;
            setState(ok ? "done" : "active");
          }}>
          {state === "submitting" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Complete consultation
        </button>
      </div>
    </Shell>
  );
}

// Order lifecycle tracker — a calm horizontal stepper (wraps on narrow).
type OrderStep = { key: string; label: string; state: "done" | "active" | "pending" };

function OrderStatus({ spec }: { spec: WidgetSpec }) {
  const label = spec.data.label ? String(spec.data.label) : "";
  const ref = spec.data.ref ? String(spec.data.ref) : "";
  const steps = Array.isArray(spec.data.steps) ? (spec.data.steps as OrderStep[]) : [];
  const color = (s: OrderStep["state"]) =>
    s === "done" ? "var(--success)" : s === "active" ? "var(--primary)" : "var(--border)";
  return (
    <Shell tone="info" icon={<PackageCheck className="h-4 w-4" />} title={spec.title ?? "Order status"}>
      {label || ref ? (
        <div className="mb-3 flex items-center gap-1 text-[13px] font-medium">
          <span>{label}</span>{ref ? <RefChip refId={ref} /> : null}
        </div>
      ) : null}
      <ol className="flex flex-wrap items-start">
        {steps.map((st, i) => {
          const active = st.state === "active";
          const done = st.state === "done";
          const dot = color(st.state);
          const next = steps[i + 1];
          return (
            <li key={st.key} aria-current={active ? "step" : undefined}
              className="flex flex-1 flex-col items-center gap-1.5" style={{ minWidth: 64 }}>
              <div className="flex w-full items-center">
                <span className="h-px flex-1" style={{ background: i === 0 ? "transparent" : dot }} />
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-colors"
                  style={{
                    borderColor: dot,
                    background: done || active ? dot : "var(--card)",
                    boxShadow: active ? "0 0 0 3px color-mix(in srgb, var(--primary) 22%, transparent)" : undefined,
                  }}>
                  {done ? <Check className="h-3 w-3" style={{ color: "var(--card)" }} /> : null}
                  {active ? <span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--card)" }} /> : null}
                </span>
                <span className="h-px flex-1" style={{ background: !next ? "transparent" : color(next.state === "pending" ? "pending" : "active") }} />
              </div>
              <span className="px-1 text-center text-[11px] leading-tight"
                style={{
                  color: st.state === "pending" ? "var(--muted-foreground)" : "var(--foreground)",
                  fontWeight: active ? 600 : 400,
                }}>{st.label}</span>
            </li>
          );
        })}
      </ol>
    </Shell>
  );
}

// Confirmation receipt — a clean label → value list.
function Receipt({ spec }: { spec: WidgetSpec }) {
  const lines = Array.isArray(spec.data.lines) ? (spec.data.lines as { label: string; value: string }[]) : [];
  const ref = spec.data.ref ? String(spec.data.ref) : "";
  const tone: "good" | "info" = spec.data.tone === "info" ? "info" : "good";
  const title = spec.title ?? (spec.data.title ? String(spec.data.title) : "Receipt");
  return (
    <Shell tone={tone} icon={<ReceiptText className="h-4 w-4" />} title={title}>
      <dl className="flex flex-col gap-1.5">
        {lines.map((ln, i) => (
          <div key={i} className="flex items-baseline justify-between gap-3 text-[13px]">
            <dt className="shrink-0" style={{ color: "var(--muted-foreground)" }}>{ln.label}</dt>
            <dd className="text-right font-semibold tabular-nums">{ln.value}</dd>
          </div>
        ))}
      </dl>
      {ref ? (
        <div className="mt-2.5 flex justify-end border-t pt-2.5" style={{ borderColor: "var(--border)" }}>
          <RefChip refId={ref} />
        </div>
      ) : null}
    </Shell>
  );
}

// Horizon-1 / S5 planner — the visible "think-itself" plan. Before it answers a
// multi-part request, the agent shows the ordered steps it will take, so the
// user sees it reason first. A clean numbered plan; when a step carries state it
// reflects progress (done / active / pending).
type PlanStep = { label: string; state?: "done" | "active" | "pending" };

function PlanSteps({ spec }: { spec: WidgetSpec }) {
  const steps = Array.isArray(spec.data.steps) ? (spec.data.steps as PlanStep[]) : [];
  return (
    <Shell tone="info" icon={<ListChecks className="h-4 w-4" />} title={spec.title ?? "My plan"}>
      <ol className="flex flex-col gap-1.5">
        {steps.map((st, i) => {
          const done = st.state === "done";
          const active = st.state === "active";
          return (
            <li key={i} aria-current={active ? "step" : undefined}
              className="flex items-start gap-2.5 text-[13px] leading-snug">
              <span className="mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-medium font-mono tabular-nums"
                style={{
                  background: active ? "var(--primary)" : "var(--muted)",
                  color: active
                    ? "var(--primary-foreground)"
                    : done ? "var(--muted-foreground)" : "var(--foreground)",
                }}>
                {done ? <Check className="h-3 w-3" /> : i + 1}
              </span>
              <span style={{
                color: done ? "var(--muted-foreground)" : "var(--foreground)",
                fontWeight: active ? 600 : 400,
              }}>{st.label}</span>
            </li>
          );
        })}
      </ol>
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
  "access-log": AccessLog,
  "consent-panel": ConsentPanel,
  "consult-session": ConsultSession,
  "order-status": OrderStatus,
  "plan-steps": PlanSteps,
  receipt: Receipt,
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
