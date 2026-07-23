/*
 * BFF export endpoint (FR-5.6). Streams the signed-in patient's OWN visit-summary
 * document from core-api — HTML (printable → Save as PDF) or the full FHIR JSON
 * bundle. The PHN comes from the session, never the client, so a patient can only
 * export their own record. core-api audits the export (07 §10 "You exported…").
 *
 * Opened via a plain link/anchor in a new tab, so the browser handles rendering
 * (HTML) or download (JSON attachment). Content-type + disposition are passed
 * through from core-api unchanged.
 */
import { getAccessToken, getSession } from "@/lib/session-store";

export const runtime = "nodejs";

function coreBase(): string {
  return (process.env.CORE_API_URL ?? "http://localhost:8001").replace(/\/$/, "");
}

export async function GET(request: Request): Promise<Response> {
  const session = await getSession();
  const token = await getAccessToken();
  if (!session?.patientPhn || !token) return new Response("unauthenticated", { status: 401 });

  const format = new URL(request.url).searchParams.get("format") === "fhir" ? "fhir" : "html";
  const url =
    `${coreBase()}/api/v1/patients/${encodeURIComponent(session.patientPhn)}` +
    `/summary/document?format=${format}`;

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      headers: { authorization: `Bearer ${token}` },
      cache: "no-store",
    });
  } catch {
    return new Response("export unavailable", { status: 502 });
  }

  const headers = new Headers();
  const ct = upstream.headers.get("content-type");
  const cd = upstream.headers.get("content-disposition");
  if (ct) headers.set("content-type", ct);
  if (cd) headers.set("content-disposition", cd);
  return new Response(upstream.body, { status: upstream.status, headers });
}
