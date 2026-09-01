/*
 * BFF vision proxy (P4b multimodal). The patient shares a photo; this attaches
 * the session's access token AND the signed-in patient's PHN server-side (never
 * from the client) and streams the agent-service /vision SSE straight back —
 * same frame protocol as /api/chat, so the concierge reuses its stream reader.
 */
import { type NextRequest } from "next/server";

import { getAccessToken, getSession } from "@/lib/session-store";

export const runtime = "nodejs";

function agentBaseUrl(): string {
  return (process.env.AGENT_SERVICE_URL ?? "http://localhost:8002").replace(/\/$/, "");
}

export async function POST(request: NextRequest): Promise<Response> {
  const session = await getSession();
  const token = await getAccessToken();
  if (!session?.patientPhn || !token) return new Response("unauthenticated", { status: 401 });

  const input = (await request.json().catch(() => ({}))) as {
    image_base64?: string; mime?: string; question?: string;
  };
  if (!input.image_base64) return new Response("image_required", { status: 422 });

  const body = JSON.stringify({
    patient_id: session.patientPhn, // from the session — never the client
    audience: "patient",
    image_base64: input.image_base64,
    mime: input.mime ?? "image/jpeg",
    question: input.question ?? "",
  });

  let upstream: Response;
  try {
    upstream = await fetch(`${agentBaseUrl()}/api/v1/vision`, {
      method: "POST",
      headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
      body,
      // @ts-expect-error — Node fetch duplex is required to stream the response
      duplex: "half",
      cache: "no-store",
    });
  } catch {
    return new Response("agent unreachable", { status: 502 });
  }

  if (!upstream.ok || !upstream.body) {
    const detail = await upstream.text().catch(() => "");
    return new Response(detail || "agent error", { status: upstream.status || 502 });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream",
      "x-vercel-ai-ui-message-stream": "v1",
      "cache-control": "no-cache",
    },
  });
}
