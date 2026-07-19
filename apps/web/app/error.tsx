"use client";

/*
 * Root error boundary — first-class per 06 §10: user-readable message,
 * retry, and a support reference. S2 wires `digest` to the OTel trace ID
 * so support can correlate (10); error messages and logs carry no PHI.
 */
import { useTranslations } from "next-intl";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@medagent/ui";

export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useTranslations("errors");

  return (
    <main className="mx-auto flex min-h-screen max-w-md items-center p-6">
      <Card className="w-full">
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground">{t("body")}</p>
          {error.digest ? (
            <p className="text-xs text-muted-foreground">
              {t("traceLabel")}: <code className="tabular-nums">{error.digest}</code>
            </p>
          ) : null}
          <Button onClick={reset}>{t("retry")}</Button>
        </CardContent>
      </Card>
    </main>
  );
}
