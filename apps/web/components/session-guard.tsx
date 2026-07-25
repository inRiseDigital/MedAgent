"use client";

/*
 * App-wide session guard. When the login session is dead (idle-timeout / expired
 * refresh token, 02 §4), the user must not be able to keep clicking around a
 * half-working app — they get a blocking dialog and a single way forward: sign
 * in again. Detection is proactive (poll + on window focus) and immediate
 * (any client fetcher can dispatch `medagent:session-expired`, e.g. the queue
 * SSE on a 401). Mounted inside authenticated layouts only, never on public
 * pages. A transient network blip does NOT lock the user out — only a real 401.
 */
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ShieldAlert } from "lucide-react";

export function SessionGuard() {
  const t = useTranslations("session");
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    let active = true;
    const markExpired = () => {
      if (active) setExpired(true);
    };
    async function check() {
      try {
        const res = await fetch("/api/auth/session", { cache: "no-store" });
        if (res.status === 401) markExpired();
      } catch {
        /* network blip — ignore; never lock out on a transient error */
      }
    }
    void check();
    const iv = setInterval(() => void check(), 45_000);
    const onVisible = () => {
      if (document.visibilityState === "visible") void check();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("medagent:session-expired", markExpired);
    return () => {
      active = false;
      clearInterval(iv);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("medagent:session-expired", markExpired);
    };
  }, []);

  if (!expired) return null;

  const returnTo =
    typeof window !== "undefined" ? window.location.pathname + window.location.search : "/";
  const loginUrl = `/api/auth/login?returnTo=${encodeURIComponent(returnTo)}`;

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="session-guard-title"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 200,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "1rem",
        background: "color-mix(in srgb, var(--background) 72%, transparent)",
        backdropFilter: "blur(4px)",
      }}
    >
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-6 text-center shadow-2xl">
        <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-destructive-surface text-destructive">
          <ShieldAlert className="h-5 w-5" />
        </div>
        <h2 id="session-guard-title" className="text-base font-semibold">
          {t("expiredTitle")}
        </h2>
        <p className="mt-1.5 text-sm text-muted-foreground">{t("expiredBody")}</p>
        <a
          href={loginUrl}
          className="mt-5 inline-flex h-10 w-full items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {t("signIn")}
        </a>
      </div>
    </div>
  );
}
