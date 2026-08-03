"use client";
/* In-app language switcher (En / Sinhala / Tamil). Sets the NEXT_LOCALE cookie
 * the next-intl request config reads, then reloads so server components re-render
 * in the chosen language. */
import { useLocale } from "next-intl";

const LOCALES: { code: string; label: string }[] = [
  { code: "en", label: "EN" },
  { code: "si", label: "සිං" },
  { code: "ta", label: "தமிழ்" },
];

export function LocaleSwitcher() {
  const active = useLocale();
  function set(code: string) {
    if (code === active) return;
    document.cookie = `NEXT_LOCALE=${code}; path=/; max-age=31536000; samesite=lax`;
    location.reload();
  }
  return (
    <div className="flex items-center gap-0.5 rounded-full border border-border bg-card p-0.5" role="group" aria-label="Language">
      {LOCALES.map((l) => (
        <button
          key={l.code}
          type="button"
          onClick={() => set(l.code)}
          aria-current={l.code === active ? "true" : undefined}
          className={`rounded-full px-2.5 py-1 text-xs font-semibold transition-colors ${
            l.code === active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {l.label}
        </button>
      ))}
    </div>
  );
}
