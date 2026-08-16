/*
 * BFF chat proxy (06 §2.2, §6). The browser posts here (cookie-authenticated,
 * same-origin); this handler attaches the session's access token server-side
 * and streams the agent-service SSE response straight back — the browser never
 * holds a bearer token, and the AI SDK data-protocol frames pass through
 * untouched so the client can render text + citation chips.
 */
import { type NextRequest } from "next/server";

import { getAccessToken } from "@/lib/session-store";

export const runtime = "nodejs";

function agentBaseUrl(): string {
  return (process.env.AGENT_SERVICE_URL ?? "http://localhost:8002").replace(/\/$/, "");
}

export async function POST(request: NextRequest): Promise<Response> {
  const token = await getAccessToken();
  if (!token) return new Response("unauthenticated", { status: 401 });

  const body = await request.text();

  let upstream: Response;
  try {
    upstream = await fetch(`${agentBaseUrl()}/api/v1/chat`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${token}`,
        "content-type": "application/json",
      },
      body,
      // @ts-expect-error — Node fetch duplex is required to stream a request/response
      duplex: "half",
      cache: "no-store",
    });
  } catch {
    return new Response("agent unreachable", { status: 502 });
  }

  // Surface a real upstream failure as a non-200 (the client shows a graceful
  // fallback on !res.ok) instead of relaying an empty body as a "successful"
  // event-stream — which would render a silent blank bubble.
  if (!upstream.ok || !upstream.body) {
    const detail = await upstream.text().catch(() => "");
    return new Response(detail || "agent error", { status: upstream.status || 502 });
  }

  // Pass the SSE stream straight through, preserving the AI SDK protocol header.
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream",
      "x-vercel-ai-ui-message-stream": "v1",
      "cache-control": "no-cache",
    },
  });
}
