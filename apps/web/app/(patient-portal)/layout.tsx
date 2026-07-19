/*
 * (patient-portal) route-group shell — S1 scaffold; docs/solution/07
 * governs. Mobile-first, 16 px+ body, one primary action per screen,
 * bottom navigation (Home · Records · Appointments · Consent · Profile)
 * and the permanent En/Si/Ta header switcher land in S5 (07 §2).
 * PWA manifest + portal-scoped service worker (07 §12.1) also S5.
 */
import type { ReactNode } from "react";

export default function PortalLayout({ children }: { children: ReactNode }) {
  return <div className="mx-auto min-h-screen max-w-lg p-4 text-base">{children}</div>;
}
