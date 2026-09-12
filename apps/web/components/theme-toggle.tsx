"use client";

/*
 * Theme control (06 §4.2) — a real light / dark / system preference.
 *
 * `medagent-theme` in localStorage is "light" | "dark" | "system" (default
 * system). Applying a choice: light/dark stamp data-theme on <html>; system
 * REMOVES the attribute so tokens.css resolves it from prefers-color-scheme
 * (which then tracks OS changes live, no listener needed). The initial value is
 * applied pre-paint by the inline script in the root layout, so there is no
 * flash; this component just reflects + flips it.
 *
 * Exports `readTheme` / `applyTheme` so other shells (the doctor rail) share the
 * exact same persistence + resolution logic.
 */
import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

export type ThemeMode = "light" | "dark" | "system";

const STORAGE_KEY = "medagent-theme";

export function readTheme(): ThemeMode {
  try {
    const t = localStorage.getItem(STORAGE_KEY);
    if (t === "light" || t === "dark" || t === "system") return t;
  } catch {
    /* private mode — non-fatal */
  }
  return "system";
}

export function applyTheme(mode: ThemeMode): void {
  const el = document.documentElement;
  if (mode === "system") el.removeAttribute("data-theme");
  else el.setAttribute("data-theme", mode);
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    /* private mode — non-fatal */
  }
}

const OPTIONS: { mode: ThemeMode; label: string; Icon: typeof Sun }[] = [
  { mode: "light", label: "Light", Icon: Sun },
  { mode: "dark", label: "Dark", Icon: Moon },
  { mode: "system", label: "System", Icon: Monitor },
];

export function ThemeToggle({ className }: { className?: string }) {
  const [mode, setMode] = useState<ThemeMode>("system");
  // Reflect the real stored value only after mount — SSR can't know it, and this
  // avoids a hydration mismatch on the pressed state.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setMode(readTheme());
    setReady(true);
  }, []);

  function choose(next: ThemeMode) {
    setMode(next);
    applyTheme(next);
  }

  return (
    <div role="group" aria-label="Theme" className={`mh-themeseg ${className ?? ""}`}>
      {OPTIONS.map(({ mode: m, label, Icon }) => {
        const active = ready && mode === m;
        return (
          <button
            key={m}
            type="button"
            onClick={() => choose(m)}
            aria-pressed={active}
            aria-label={`${label} theme`}
            title={`${label} theme`}
            data-active={active}
            className="mh-themeseg-btn"
          >
            <Icon className="h-4 w-4" aria-hidden />
          </button>
        );
      })}
    </div>
  );
}
