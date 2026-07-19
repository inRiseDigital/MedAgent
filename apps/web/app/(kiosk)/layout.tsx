/*
 * (kiosk) route-group shell — S1 scaffold; 05 §5 and 06 §1 govern.
 * Fullscreen, chrome-less, no navigation: a shared reception device is
 * never a browsing surface. Kiosk stations authenticate with a
 * station-scoped device service account, never a clinician's personal
 * credential (06 §2.2) — wired in S2.
 */
import type { ReactNode } from "react";

export default function KioskLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-8">
      {children}
    </div>
  );
}
