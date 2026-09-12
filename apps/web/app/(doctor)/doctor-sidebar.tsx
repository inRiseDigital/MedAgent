"use client";

/*
 * Doctor app-shell sidebar (06 §1). Replaces the old top header + icon rail:
 * a single collapsible left rail that carries the brand, primary navigation,
 * and — pinned to the bottom — the account controls (theme, profile, sign-out).
 * Collapse state and theme are persisted client-side; nav data + labels are
 * passed in from the server layout (which owns i18n + role gating).
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  Activity,
  LayoutList,
  LogOut,
  Monitor,
  Moon,
  PanelLeft,
  PanelLeftClose,
  Send,
  Sun,
  Users,
  type LucideIcon,
} from "lucide-react";

import { applyTheme, readTheme, type ThemeMode } from "@/components/theme-toggle";

export type NavIcon = "queue" | "patients" | "referrals" | "dashboard";
const ICONS: Record<NavIcon, LucideIcon> = {
  queue: LayoutList,
  patients: Users,
  referrals: Send,
  dashboard: Activity,
};

export interface DoctorNavItem {
  href: string;
  label: string;
  icon: NavIcon;
}

// Light · dark · system, cycled from one compact rail button (the segmented
// control needs more width than the collapsed rail has). Shares persistence +
// resolution with the ThemeToggle via the exported helpers.
const THEME_ICON: Record<ThemeMode, LucideIcon> = { light: Sun, dark: Moon, system: Monitor };
const THEME_LABEL: Record<ThemeMode, string> = { light: "Light", dark: "Dark", system: "System" };
const THEME_NEXT: Record<ThemeMode, ThemeMode> = { system: "light", light: "dark", dark: "system" };

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[parts.length - 1]?.[0] ?? "")).toUpperCase() || "?";
}

export function DoctorSidebar({
  appName,
  items,
  displayName,
  roleLabel,
  signOutLabel,
}: {
  appName: string;
  items: DoctorNavItem[];
  displayName: string;
  roleLabel: string;
  signOutLabel: string;
}) {
  const pathname = usePathname();
  const [open, setOpen] = useState(true);
  const [theme, setTheme] = useState<ThemeMode>("system");
  const [ready, setReady] = useState(false);
  // The user's saved preference — only honoured on wide screens. Below the
  // desktop breakpoint the rail always auto-collapses to icons so the content
  // (chat + record) gets the width it needs (e.g. a folded phone / small split).
  const prefRef = useRef(true);

  useEffect(() => {
    try {
      const nav = localStorage.getItem("medagent-nav");
      if (nav) prefRef.current = nav === "open";
    } catch {
      /* private mode — non-fatal */
    }
    const wide = window.matchMedia("(min-width: 1024px)");
    const apply = () => setOpen(wide.matches ? prefRef.current : false);
    apply();
    wide.addEventListener("change", apply);
    setTheme(readTheme());
    setReady(true);
    return () => wide.removeEventListener("change", apply);
  }, []);

  function toggleNav() {
    setOpen((o) => {
      const next = !o;
      // Persist as the preference only on wide screens — a narrow-screen toggle
      // is a transient peek, not a new default.
      if (window.matchMedia("(min-width: 1024px)").matches) {
        prefRef.current = next;
        try {
          localStorage.setItem("medagent-nav", next ? "open" : "closed");
        } catch {
          /* non-fatal */
        }
      }
      return next;
    });
  }

  function cycleTheme() {
    const next = THEME_NEXT[theme];
    setTheme(next);
    applyTheme(next);
  }

  // Avoid a first-paint flash: pre-hydration, mirror the responsive default —
  // collapsed below the desktop breakpoint, expanded at lg+.
  const width = !ready ? "w-16 lg:w-60" : open ? "w-60" : "w-16";

  return (
    <nav
      aria-label={appName}
      data-open={open}
      className={`group/nav flex shrink-0 flex-col border-r border-border bg-card transition-[width] duration-200 ease-out ${width}`}
    >
      {/* Brand + collapse toggle */}
      <div className={`flex h-14 items-center gap-2 px-3 ${open ? "" : "justify-center"}`}>
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Activity className="h-4 w-4" />
        </span>
        {open ? <span className="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight">{appName}</span> : null}
        <button
          type="button"
          onClick={toggleNav}
          aria-label={open ? "Collapse sidebar" : "Expand sidebar"}
          title={open ? "Collapse" : "Expand"}
          className={`inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${open ? "" : "hidden"}`}
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>
      {!open ? (
        <button
          type="button"
          onClick={toggleNav}
          aria-label="Expand sidebar"
          title="Expand"
          className="mx-auto mb-1 inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <PanelLeft className="h-4 w-4" />
        </button>
      ) : null}

      {/* Primary navigation */}
      <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto p-2">
        {items.map(({ href, label, icon }) => {
          const Icon = ICONS[icon];
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              title={open ? undefined : label}
              aria-current={active ? "page" : undefined}
              className={`flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                active ? "bg-primary/12 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"
              } ${open ? "" : "justify-center"}`}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {open ? <span className="truncate">{label}</span> : null}
            </Link>
          );
        })}
      </div>

      {/* Account controls — pinned to the bottom */}
      <div className="flex flex-col gap-1 border-t border-border p-2">
        {(() => {
          const ThemeIcon = THEME_ICON[theme];
          return (
            <button
              type="button"
              onClick={cycleTheme}
              aria-label={`Theme: ${THEME_LABEL[theme]}. Switch to ${THEME_LABEL[THEME_NEXT[theme]]}.`}
              title={`Theme: ${THEME_LABEL[theme]}`}
              className={`flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${open ? "" : "justify-center"}`}
            >
              <ThemeIcon className="h-4 w-4 shrink-0" />
              {open ? <span className="truncate">{`${THEME_LABEL[theme]} theme`}</span> : null}
            </button>
          );
        })()}

        <div
          title={open ? undefined : `${displayName} · ${roleLabel}`}
          className={`flex items-center gap-2.5 rounded-lg px-2 py-2 ${open ? "" : "justify-center"}`}
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
            {initials(displayName)}
          </span>
          {open ? (
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold leading-tight">{displayName}</div>
              <div className="truncate text-xs text-muted-foreground">{roleLabel}</div>
            </div>
          ) : null}
        </div>

        <form action="/api/auth/logout" method="POST">
          <button
            type="submit"
            title={open ? undefined : signOutLabel}
            className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-destructive-surface hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${open ? "" : "justify-center"}`}
          >
            <LogOut className="h-4 w-4 shrink-0" />
            {open ? <span className="truncate">{signOutLabel}</span> : null}
          </button>
        </form>
      </div>
    </nav>
  );
}
