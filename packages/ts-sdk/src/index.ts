/*
 * @medagent/ts-sdk — typed fetch wrappers over the generated OpenAPI types.
 *
 * S1 scaffold — the generated `paths` types do not exist until
 * `pnpm --filter @medagent/ts-sdk generate` has run against live services
 * (see scripts/generate.mjs), so this module is generic over the `paths`
 * shape rather than importing from ./generated directly. Containers in
 * apps/web instantiate concrete clients like:
 *
 *   import type { paths as CoreApiPaths } from "@medagent/ts-sdk/generated/core-api";
 *   const coreApi = createClient<CoreApiPaths>({ baseUrl: env.CORE_API_URL });
 *
 * Per 06 ADR W-5 / §8 rule 3, this package is the ONLY HTTP surface for
 * apps/web — hand-written fetch is lint-banned outside the two BFF proxy
 * routes. Response-body narrowing per operation (openapi-fetch-grade
 * typing) is completed in S2 once generated schemas are committed.
 */

export type HttpMethod = "get" | "post" | "put" | "patch" | "delete";

export interface ClientOptions {
  /** Service base URL, e.g. http://localhost:8001 (server-side: from env). */
  baseUrl: string;
  /** Override fetch (tests/MSW, or a server-side fetch that attaches the session's bearer token — 06 §2.2). */
  fetchImpl?: typeof fetch;
  /** Called per request; merge point for Authorization headers in the BFF. */
  headers?: () => HeadersInit | Promise<HeadersInit>;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly url: string,
    public readonly body: unknown,
  ) {
    super(`API request failed: ${status} ${url}`);
    this.name = "ApiError";
  }
}

export interface RequestInitEx {
  /** Path params substituted into `{placeholders}` in the path template. */
  params?: Record<string, string | number>;
  /** Query string entries; undefined values are skipped. */
  query?: Record<string, string | number | boolean | undefined>;
  /** JSON request body. */
  body?: unknown;
  signal?: AbortSignal;
}

export interface Client<Paths> {
  request<T = unknown>(method: HttpMethod, path: keyof Paths & string, init?: RequestInitEx): Promise<T>;
  get<T = unknown>(path: keyof Paths & string, init?: RequestInitEx): Promise<T>;
  post<T = unknown>(path: keyof Paths & string, init?: RequestInitEx): Promise<T>;
}

/** Build a typed client for one service. `Paths` comes from ./generated/*. */
export function createClient<Paths>(options: ClientOptions): Client<Paths> {
  const fetchImpl = options.fetchImpl ?? fetch;

  async function request<T>(
    method: HttpMethod,
    path: keyof Paths & string,
    init: RequestInitEx = {},
  ): Promise<T> {
    let resolved: string = path;
    for (const [key, value] of Object.entries(init.params ?? {})) {
      resolved = resolved.replace(`{${key}}`, encodeURIComponent(String(value)));
    }
    const url = new URL(resolved, options.baseUrl);
    for (const [key, value] of Object.entries(init.query ?? {})) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }

    const headers = new Headers(await options.headers?.());
    if (init.body !== undefined && !headers.has("content-type")) {
      headers.set("content-type", "application/json");
    }

    const res = await fetchImpl(url, {
      method: method.toUpperCase(),
      headers,
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
      signal: init.signal,
    });

    const isJson = res.headers.get("content-type")?.includes("application/json") ?? false;
    const payload: unknown = res.status === 204 ? undefined : isJson ? await res.json() : await res.text();

    if (!res.ok) throw new ApiError(res.status, url.toString(), payload);
    return payload as T;
  }

  return {
    request,
    get: (path, init) => request("get", path, init),
    post: (path, init) => request("post", path, init),
  };
}
