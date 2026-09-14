/*
 * (patient-portal) route-group shell — docs/solution/07 governs. Mobile-first,
 * 16 px+ body, calm and low-literacy-first. A light top bar carries the brand
 * and the light/dark toggle; the permanent En/Si/Ta switcher + bottom nav +
 * PWA manifest land with the fuller portal build (07 §2).
 */
import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";
import { HeartPulse, Settings2 } from "lucide-react";

import { SessionGuard } from "@/components/session-guard";
import { SignOutButton } from "@/components/sign-out-button";
import { ThemeToggle } from "@/components/theme-toggle";
import { PATIENT, requireRoles } from "@/lib/require-role";
import { LocaleSwitcher } from "./portal/locale-switcher";
import { Notifications } from "./portal/notifications";
import "../mh-theme.css";

export default async function PortalLayout({ children }: { children: ReactNode }) {
  const tc = await getTranslations("common");
  const tn = await getTranslations("nav");
  // Portal is for patients/guardians only — a staff session is bounced to /queue.
  await requireRoles(PATIENT);
  return (
    <div className="mh min-h-screen">
      <SessionGuard />
      <Notifications />
      <header className="sticky top-0 z-30 bg-[color:var(--mh-bg)]/70 backdrop-blur-md">
        <div className="mx-auto flex max-w-lg items-center justify-between px-4 py-3 md:max-w-4xl lg:max-w-6xl 2xl:max-w-[1600px]">
          <span className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-[var(--mh-shadow)]">
              <HeartPulse className="h-4 w-4" />
            </span>
            <span className="text-[17px] font-extrabold tracking-tight">{tc("appName")}</span>
          </span>
          {/* One quiet account menu instead of a crowded row of controls. */}
          <details className="relative [&_summary::-webkit-details-marker]:hidden">
            <summary className="flex h-9 w-9 cursor-pointer list-none items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label="Settings & account">
              <Settings2 className="h-[18px] w-[18px]" />
            </summary>
            <div className="absolute right-0 top-11 z-40 flex w-60 flex-col gap-3 rounded-2xl border border-border bg-card p-3.5 shadow-[var(--mh-shadow-lg)]">
              <div className="flex flex-col gap-1.5">
                <span className="px-0.5 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Appearance</span>
                <ThemeToggle />
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="px-0.5 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Language</span>
                <LocaleSwitcher />
              </div>
              <div className="border-t border-border pt-2.5"><SignOutButton label={tn("signOut")} /></div>
            </div>
          </details>
        </div>
      </header>
      <div className="mx-auto max-w-lg px-4 pb-4 pt-3 text-base md:max-w-4xl lg:max-w-6xl 2xl:max-w-[1600px]">{children}</div>
    </div>
  );
}
