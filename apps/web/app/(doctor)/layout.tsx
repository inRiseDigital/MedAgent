/*
 * (doctor) route-group shell (06 §1). Fixed top header (brand + theme toggle)
 * and an icon sidebar; content scrolls independently. Route-group access is
 * gated server-side in proxy.ts (06 §2.2). Clinical density: 14 px body,
 * compact rows (06 §4.3). Theme-aware throughout — no palette literals.
 */
import Link from "next/link";
import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";
import { Activity, LayoutList, Send, Users } from "lucide-react";

import { SessionGuard } from "@/components/session-guard";
import { ThemeToggle } from "@/components/theme-toggle";

export default async function DoctorLayout({ children }: { children: ReactNode }) {
  const t = await getTranslations("nav");
  const tc = await getTranslations("common");

  const navItems = [
    { href: "/queue", label: t("queue"), Icon: LayoutList },
    { href: "/patients", label: t("patients"), Icon: Users },
    { href: "/referrals", label: t("referrals"), Icon: Send },
    { href: "/dashboard", label: t("dashboard"), Icon: Activity },
  ];

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SessionGuard />
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:ring-2 focus:ring-ring"
      >
        {t("skipToContent")}
      </a>

      {/* Top header — brand left, controls right. */}
      <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between border-b border-border bg-card/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-card/80">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Activity className="h-4 w-4" />
          </span>
          <span className="text-sm font-semibold tracking-tight">{tc("appName")}</span>
          <span className="ml-1 hidden rounded bg-muted px-1.5 py-0.5 text-[0.65rem] font-medium uppercase tracking-wide text-muted-foreground sm:inline">
            Clinician
          </span>
        </div>
        <ThemeToggle />
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Sidebar */}
        <nav
          aria-label={tc("appName")}
          className="flex w-16 shrink-0 flex-col gap-1 border-r border-border bg-card p-2 sm:w-52 sm:p-3"
        >
          {navItems.map(({ href, label, Icon }) => (
            <Link
              key={href}
              href={href}
              className="flex items-center gap-3 rounded-md px-2.5 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="hidden sm:inline">{label}</span>
            </Link>
          ))}
        </nav>

        <main id="main" className="min-w-0 flex-1 overflow-x-hidden p-4 sm:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
