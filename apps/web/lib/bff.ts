/*
 * Shared BFF proxy helpers (P4.1). Every route handler under app/api/* was
 * re-implementing the same trio: an env base-URL reader, the fetch with the
 * session token attached server-side, and a status+body pass-through. This
 * centralises that so there is one place to get the token-attach and error
 * handling right — the browser never holds a bearer.
 */
import { NextResponse } from "next/server";

export function coreBase(): string {
  return (process.env.CORE_API_URL ?? "http://localhost:8001").replace(/\/$/, "");
}

export function agentBase(): string {
  return (process.env.AGENT_SERVICE_URL ?? "http://localhost:8002").replace(/\/$/, "");
}

/** Pass an upstream JSON response through unchanged (status + body). */
export async function passThroughJson(upstream: Response): Promise<NextResponse> {
  return new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}

interface ProxyInit {
  token: string;
  method?: string;
  /** Pre-serialised JSON body (sets content-type + method POST when present). */
  body?: string;
}

/**
 * Proxy a JSON request to a core-api path with the session token attached, and
 * pass the upstream status + body straight back. An unreachable core-api becomes
 * a clean 502 rather than an unhandled throw.
 */
export async function proxyToCore(path: string, init: ProxyInit): Promise<NextResponse> {
  let upstream: Response;
  try {
    upstream = await fetch(`${coreBase()}${path}`, {
      method: init.method ?? (init.body ? "POST" : "GET"),
      headers: {
        authorization: `Bearer ${init.token}`,
        ...(init.body ? { "content-type": "application/json" } : {}),
      },
      body: init.body,
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "core_api_unreachable" }, { status: 502 });
  }
  return passThroughJson(upstream);
}
