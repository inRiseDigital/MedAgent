/*
 * Root not-found — first-class per 06 §10. Route groups add their own
 * (portal/kiosk audiences get audience-appropriate copy) in S2.
 */
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Card, CardContent, CardHeader, CardTitle } from "@medagent/ui";

export default async function NotFound() {
  const t = await getTranslations("notFound");

  return (
    <main className="mx-auto flex min-h-screen max-w-md items-center p-6">
      <Card className="w-full">
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground">{t("body")}</p>
          <Link className="text-primary underline-offset-4 hover:underline" href="/queue">
            {t("backToQueue")}
          </Link>
        </CardContent>
      </Card>
    </main>
  );
}
