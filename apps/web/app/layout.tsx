import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { Inter, JetBrains_Mono } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import { Providers } from "./providers";
import { PwaRegister } from "./pwa-register";
import "./globals.css";

/*
 * Typography (06 §4.3, the standing next/font TODO). Inter is the UI/text face —
 * a clean, high-legibility grotesque that carries the sleek conversational look;
 * JetBrains Mono is the data face for tabular numbers, citations and codes.
 * Both are self-hosted by next/font (no layout-shift, no network at runtime) and
 * exposed as CSS variables that tokens.css maps onto `--font` / `--font-mono`.
 */
const fontSans = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});
const fontMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-jetbrains",
});

export const metadata: Metadata = {
  title: "MedAgent",
  description: "MedAgent platform — doctor workspace, patient portal and check-in kiosk.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.svg", apple: "/icon.svg" },
  appleWebApp: { capable: true, title: "MedAgent", statusBarStyle: "black-translucent" },
};

export const viewport: Viewport = {
  themeColor: "#000000",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
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
    <html lang={locale} data-theme="light" className={`${fontSans.variable} ${fontMono.variable}`} suppressHydrationWarning>
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
        <PwaRegister />
      </body>
    </html>
  );
}
