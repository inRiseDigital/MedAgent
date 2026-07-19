/*
 * S1 scaffold — presentational only (06 §8). 1-px borders over heavy
 * shadows; whitespace communicates grouping (06 §4.3).
 */
import type { ComponentPropsWithRef } from "react";
import { cx } from "./cx";

export function Card({ className, ...props }: ComponentPropsWithRef<"div">) {
  return (
    <div
      className={cx("rounded-lg border border-border bg-card text-card-foreground", className)}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: ComponentPropsWithRef<"div">) {
  return <div className={cx("flex flex-col gap-1 border-b border-border p-4", className)} {...props} />;
}

export function CardTitle({ className, ...props }: ComponentPropsWithRef<"h2">) {
  return <h2 className={cx("text-sm font-semibold", className)} {...props} />;
}

export function CardContent({ className, ...props }: ComponentPropsWithRef<"div">) {
  return <div className={cx("p-4", className)} {...props} />;
}
