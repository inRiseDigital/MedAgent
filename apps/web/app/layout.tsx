import type { Metadata } from "next";
import type { ReactNode } from "react";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "MedAgent",
  description: "MedAgent platform — doctor workspace, patient portal and check-in kiosk.",
};

/*
 * Root layout — S1 scaffold (docs/solution/06 §1).
 * - next-intl provider wraps everything; all strings come from
 *   messages/{locale}.json (06 §9, scaffolded day 1).
 * - Theme: light by default; dark mode is data-theme="dark" on <html>,
 *   which swaps the token values (tokens.css) and activates Tailwind
 *   `dark:` variants. The user-facing toggle + persisted preference land
 *   in S2 — the mechanism is complete now so no component ever hard-codes
 *   palette values (ADR W-3, no !important anywhere).
 * - Latin + Sinhala + Tamil typefaces (Noto Sans companions, 06 §4.3) are
 *   wired via next/font when the locale switcher lands.
 */
export default async function RootLayout({ children }: { children: ReactNode }) {
  const locale = await getLocale();
  const messages = await getMessages();

  return (
    <html lang={locale} data-theme="light" suppressHydrationWarning>
      <head>
        {/* Apply the persisted theme before first paint (no flash). Reads the
            same key the ThemeToggle writes; falls back to the OS preference. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('medagent-theme');if(!t){t=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}document.documentElement.setAttribute('data-theme',t);}catch(e){}})();`,
          }}
        />
      </head>
      <body className="min-h-screen bg-background text-foreground">
        <NextIntlClientProvider locale={locale} messages={messages}>
          <Providers>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
