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
  // Adapts the browser/OS chrome to the resolved theme (light canvas vs the
  // near-black premium dark). An explicit user choice is applied to <html> by
  // the pre-paint script below; this covers the system case.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f8fafc" },
    { media: "(prefers-color-scheme: dark)", color: "#000000" },
  ],
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

/*
 * Root layout — S1 scaffold (docs/solution/06 §1).
 * - next-intl provider wraps everything; all strings come from
 *   messages/{locale}.json (06 §9, scaffolded day 1).
 * - Theme: a real light / dark / system preference. `medagent-theme` in
 *   localStorage is "light" | "dark" | "system" (default system). The pre-paint
 *   script below applies it to <html> before first paint: an explicit choice
 *   sets data-theme; "system" (or unset) REMOVES the attribute so tokens.css
 *   resolves it live from prefers-color-scheme. The ThemeToggle keeps this in
 *   sync. No component hard-codes palette values (ADR W-3, no !important).
 * - Latin + Sinhala + Tamil typefaces (Noto Sans companions, 06 §4.3) are
 *   wired via next/font when the locale switcher lands.
 */
export default async function RootLayout({ children }: { children: ReactNode }) {
  const locale = await getLocale();
  const messages = await getMessages();

  return (
    <html lang={locale} data-theme="light" className={`${fontSans.variable} ${fontMono.variable}`} suppressHydrationWarning>
      <head>
        {/* Apply the persisted theme before first paint (no flash-of-wrong-theme).
            Reads the same key the ThemeToggle writes: an explicit light/dark
            choice is stamped on <html>; "system" (or unset) removes the attribute
            so tokens.css resolves it from prefers-color-scheme (and tracks OS
            changes live, with no JS). */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('medagent-theme');var e=document.documentElement;if(t==='light'||t==='dark'){e.setAttribute('data-theme',t);}else{e.removeAttribute('data-theme');}}catch(_){}})();`,
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
