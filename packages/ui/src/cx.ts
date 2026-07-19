/** Minimal class-name joiner — avoids a clsx dependency for S1. */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
