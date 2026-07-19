/*
 * S1 scaffold — presentational only (06 §8). Note: route-level loading
 * states use layout-matching skeletons, not spinners-on-white (06 §10);
 * this spinner is for small inline waits (buttons, chips).
 */
import { LoaderCircle } from "lucide-react";
import { cx } from "./cx";

export interface SpinnerProps {
  /** Accessible status text, announced to screen readers. */
  label: string;
  size?: "sm" | "md";
  className?: string;
}

export function Spinner({ label, size = "md", className }: SpinnerProps) {
  return (
    <span role="status" className={cx("inline-flex items-center", className)}>
      <LoaderCircle
        aria-hidden="true"
        strokeWidth={1.5}
        className={cx("animate-spin text-muted-foreground", size === "sm" ? "h-4 w-4" : "h-5 w-5")}
      />
      <span className="sr-only">{label}</span>
    </span>
  );
}
