/*
 * (doctor) route-group shell (06 §1). A fixed full-height app shell: one
 * collapsible left sidebar carries the brand, navigation, and account controls
 * (theme / profile / sign-out) — no top header — and the content area is the
 * only scroll region. Route-group access is gated server-side in proxy.ts
 * (06 §2.2). Theme-aware throughout — no palette literals.
 */
import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";

import { SessionGuard } from "@/components/session-guard";
import "../mh-theme.css";
import { CLINICAL, requireRoles, STAFF } from "@/lib/require-role";
import { DoctorSidebar, type DoctorNavItem } from "./doctor-sidebar";

export default async function DoctorLayout({ children }: { children: ReactNode }) {
  const t = await getTranslations("nav");
  const tc = await getTranslations("common");

  // Staff-only route group: a patient/guardian session is bounced to the portal.
  const session = await requireRoles(STAFF);
  const isClinician = session.roles.some((r) => CLINICAL.includes(r));
  const isReceptionist = session.roles.includes("receptionist");

  // Receptionist: demographics + queue only, never clinical surfaces (02 §3).
  const navItems: (DoctorNavItem & { show: boolean })[] = [
    { href: "/queue", label: t("queue"), icon: "queue", show: true },
    { href: "/patients", label: t("patients"), icon: "patients", show: true },
    { href: "/referrals", label: t("referrals"), icon: "referrals", show: isClinician },
    { href: "/dashboard", label: t("dashboard"), icon: "dashboard", show: isClinician },
  ];
  const items = navItems.filter((i) => i.show).map(({ show: _show, ...i }) => i);
  const roleLabel = isClinician ? "Clinician" : isReceptionist ? "Reception" : "Staff";

  return (
    <div className="mh flex h-screen overflow-hidden bg-background">
      <SessionGuard />
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:ring-2 focus:ring-ring"
      >
        {t("skipToContent")}
      </a>

      <DoctorSidebar
        appName={tc("appName")}
        items={items}
        displayName={session.displayName}
        roleLabel={roleLabel}
        signOutLabel={t("signOut")}
      />

      <main id="main" className="min-w-0 flex-1 overflow-y-auto p-4 sm:p-6">
        {children}
      </main>
    </div>
  );
}
