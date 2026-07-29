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

export default async function PortalLayout({ children }: { children: ReactNode }) {
  const tc = await getTranslations("common");
  const tn = await getTranslations("nav");
  // Portal is for patients/guardians only — a staff session is bounced to /queue.
  await requireRoles(PATIENT);
  return (
    <div className="min-h-screen bg-background">
      <SessionGuard />
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-lg items-center justify-between px-4 py-3">
          <span className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <HeartPulse className="h-4 w-4" />
            </span>
            <span className="text-base font-semibold tracking-tight">{tc("appName")}</span>
          </span>
          <span className="flex items-center gap-2">
            <ThemeToggle />
            <SignOutButton label={tn("signOut")} />
          </span>
        </div>
      </header>
      <div className="mx-auto max-w-lg p-4 text-base">{children}</div>
    </div>
  );
}
