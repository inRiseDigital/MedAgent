/*
 * (patient-portal) route-group shell — docs/solution/07 governs. Mobile-first,
 * 16 px+ body, calm and low-literacy-first. A light top bar carries the brand
 * and the light/dark toggle; the permanent En/Si/Ta switcher + bottom nav +
 * PWA manifest land with the fuller portal build (07 §2).
 */
import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";
import { HeartPulse } from "lucide-react";

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
      <header className="sticky top-0 z-20 border-b border-border bg-[color:var(--mh-bg)]/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-lg items-center justify-between px-4 py-3 md:max-w-4xl lg:max-w-6xl 2xl:max-w-[1600px]">
          <span className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <HeartPulse className="h-4 w-4" />
            </span>
            <span className="text-base font-semibold tracking-tight">{tc("appName")}</span>
          </span>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <LocaleSwitcher />
            <SignOutButton label={tn("signOut")} />
          </div>
        </div>
      </header>
      <div className="mx-auto max-w-lg px-4 pb-4 pt-3 text-base md:max-w-4xl lg:max-w-6xl 2xl:max-w-[1600px]">{children}</div>
    </div>
  );
}
