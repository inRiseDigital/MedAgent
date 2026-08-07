/*
 * next-intl request config — scaffolded day 1 (docs/solution/06 §9, locked
 * decision; NFR-7). Every user-visible string lives in messages/*.json from
 * the first commit; hard-coded JSX strings become a lint failure in S2.
 *
 * S1: fixed `en` locale. /{locale}/… routing with en default (si/ta
 * switchable) lands with the locale switcher; si/ta catalogues are
 * keys-complete from S1 (values English until Phase B translation) so
 * switching locale never crashes.
 */
import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

export const SUPPORTED_LOCALES = ["en", "si", "ta"] as const;
export type AppLocale = (typeof SUPPORTED_LOCALES)[number];
export const LOCALE_COOKIE = "NEXT_LOCALE";

export default getRequestConfig(async () => {
  // Only the patient portal follows the language switch; the clinician workspace
  // is English-standardised. proxy.ts tags patient requests with x-mh-i18n.
  let locale: AppLocale = "en";
  const scope = (await headers()).get("x-mh-i18n");
  if (scope === "patient") {
    const requested = (await cookies()).get(LOCALE_COOKIE)?.value ?? "";
    if ((SUPPORTED_LOCALES as readonly string[]).includes(requested)) locale = requested as AppLocale;
  }
  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default,
  };
});
