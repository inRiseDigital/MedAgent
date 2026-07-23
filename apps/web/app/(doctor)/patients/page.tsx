/*
 * Patient search (FR-2.4, 06 §5). Server component: reads the `q` query param,
 * searches the MPI through the BFF and lists demographic matches. A single
 * smart box — a query with letters searches by name; a numeric query searches
 * PHN and phone together (a desk reality: staff type whichever they have).
 *
 * Results are demographics only. Opening a match navigates to /patients/{phn},
 * where the care-relationship grant is enforced before any clinical data loads
 * (02 §7). No result here implies any access to a record.
 */
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@medagent/ui";

import { searchPatients, ApiError, type PatientSearchResult } from "@/lib/api";

export const dynamic = "force-dynamic";

function dedupeByPhn(lists: PatientSearchResult[][]): PatientSearchResult[] {
  const seen = new Map<string, PatientSearchResult>();
  for (const list of lists) for (const r of list) if (!seen.has(r.phn)) seen.set(r.phn, r);
  return [...seen.values()];
}

export default async function PatientSearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const t = await getTranslations("search");
  const { q } = await searchParams;
  const query = (q ?? "").trim();
  const hasQuery = query.length >= 2;

  let results: PatientSearchResult[] = [];
  let error = false;
  if (hasQuery) {
    const isNumeric = /^[0-9\s-]+$/.test(query);
    try {
      if (isNumeric) {
        // Could be a PHN or a phone/NIC — try both; an invalid-PHN 422 is not
        // an error, just "not a PHN", so fall through to the phone match.
        const [byPhn, byPhone] = await Promise.all([
          searchPatients({ phn: query }).catch((e) => {
            if (e instanceof ApiError && e.status === 422) return [] as PatientSearchResult[];
            throw e;
          }),
          searchPatients({ phone: query }),
        ]);
        results = dedupeByPhn([byPhn, byPhone]);
      } else {
        results = await searchPatients({ name: query });
      }
    } catch {
      error = true;
    }
  }

  return (
    <main className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold">{t("title")}</h1>
        <p className="text-muted-foreground">{t("description")}</p>
      </div>

      {/* Plain GET form — navigation sets ?q=, no client JS needed. */}
      <form method="GET" role="search" className="flex gap-2">
        <input
          type="search"
          name="q"
          defaultValue={query}
          autoFocus
          placeholder={t("placeholder")}
          aria-label={t("placeholder")}
          className="min-w-0 flex-1 rounded-md border border-border bg-card px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <button
          type="submit"
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {t("submit")}
        </button>
      </form>

      {!hasQuery ? (
        <p className="text-sm text-muted-foreground">{t("hint")}</p>
      ) : error ? (
        <Card>
          <CardContent className="py-6">
            <p className="text-muted-foreground">{t("error")}</p>
          </CardContent>
        </Card>
      ) : results.length === 0 ? (
        <Card>
          <CardContent className="py-6">
            <p className="text-muted-foreground">{t("empty", { query })}</p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("resultsTitle", { count: results.length })}</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y divide-border">
              {results.map((r) => {
                const name = (r.demographics.name as string) || t("unnamed");
                const phone = r.demographics.phone as string | undefined;
                const sex = r.demographics.sex as string | undefined;
                return (
                  <li key={r.phn}>
                    <Link
                      href={`/patients/${encodeURIComponent(r.phn)}`}
                      className="flex items-center justify-between gap-3 px-4 py-3 text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <span className="min-w-0">
                        <span className="font-medium">{name}</span>
                        <span className="ml-2 text-muted-foreground tabular-nums">
                          {r.phn_display}
                        </span>
                        {sex ? <span className="ml-2 text-muted-foreground">· {sex}</span> : null}
                        {phone ? (
                          <span className="ml-2 text-muted-foreground tabular-nums">· {phone}</span>
                        ) : null}
                      </span>
                      {r.face_consent ? (
                        <Badge variant="pass">{t("faceOn")}</Badge>
                      ) : (
                        <Badge variant="warn">{t("faceOff")}</Badge>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      )}
    </main>
  );
}
