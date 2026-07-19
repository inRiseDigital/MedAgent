/*
 * S1 scaffold — presentational only (06 §8). Status variants map to the
 * Rx-safety verdict states pass/warn/block (06 §7) plus a neutral default.
 * "Never colour alone" (06 §4.5): every non-neutral variant pairs colour
 * with an icon, and the label is always text.
 */
import type { ComponentPropsWithRef } from "react";
import { Ban, CheckCircle2, TriangleAlert } from "lucide-react";
import { cx } from "./cx";

type BadgeVariant = "neutral" | "pass" | "warn" | "block";

export interface BadgeProps extends ComponentPropsWithRef<"span"> {
  variant?: BadgeVariant;
}

const VARIANT: Record<BadgeVariant, string> = {
  neutral: "border-border bg-muted text-muted-foreground",
  pass: "border-success bg-success-surface text-success",
  warn: "border-warning bg-warning-surface text-warning",
  block: "border-destructive bg-destructive-surface text-destructive",
};

const ICON: Record<BadgeVariant, typeof CheckCircle2 | null> = {
  neutral: null,
  pass: CheckCircle2,
  warn: TriangleAlert,
  block: Ban,
};

export function Badge({ variant = "neutral", className, children, ...props }: BadgeProps) {
  const Icon = ICON[variant];
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs font-medium",
        VARIANT[variant],
        className,
      )}
      {...props}
    >
      {Icon ? <Icon aria-hidden="true" className="h-3 w-3" strokeWidth={1.5} /> : null}
      {children}
    </span>
  );
}
