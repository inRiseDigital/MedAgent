/*
 * (doctor) route-group shell — S1 scaffold per 06 §1: sidebar,
 * event-stream provider and session context land in S2/S3
 * (docs/solution/11). Route-group access is gated server-side in proxy.ts
 * (06 §2.2). Density: 14 px clinical body, compact rows (06 §4.3).
 */
import Link from "next/link";
import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";

export default async function DoctorLayout({ children }: { children: ReactNode }) {
  const t = await getTranslations("nav");
  const tc = await getTranslations("common");

  return (
    <div className="flex min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:ring-2 focus:ring-ring"
      >
        {t("skipToContent")}
      </a>

      {/* Sidebar shell — auto-collapse on patient-session entry (ported
          prototype behaviour) arrives with the session screens in S3. */}
      <nav
        aria-label={tc("appName")}
        className="flex w-56 shrink-0 flex-col gap-1 border-r border-border bg-card p-3"
      >
        <p className="px-2 py-3 text-sm font-semibold">{tc("appName")}</p>
        <Link
          href="/queue"
          className="rounded-md px-2 py-2 text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {t("queue")}
        </Link>
        {/* /day, /patients (search), /proposals join here as their routes
            land — S3/S4 per docs/solution/11. */}
      </nav>

      <main id="main" className="min-w-0 flex-1 p-6">
        {children}
      </main>
    </div>
  );
}
