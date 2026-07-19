/*
 * Patient portal home — S1 scaffold, implemented in S5 per
 * docs/solution/11 and 07 §5: upcoming appointment, active medications,
 * unread results/summaries and pending actions surface here, fetched
 * through core-api patient-scoped endpoints via @medagent/ts-sdk.
 * Plain-language, low-literacy-first design (07 §12.3).
 */
import { getTranslations } from "next-intl/server";
import { Card, CardContent, CardHeader, CardTitle } from "@medagent/ui";

export default async function PortalHomePage() {
  const t = await getTranslations("portal");

  return (
    <main className="space-y-4 py-4">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-muted-foreground">{t("greeting")}</p>
          <p className="text-muted-foreground">{t("languageNote")}</p>
        </CardContent>
      </Card>
    </main>
  );
}
