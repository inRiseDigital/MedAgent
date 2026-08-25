import { afterEach, describe, expect, it, vi } from "vitest";

import { coreBase, proxyToCore } from "@/lib/bff";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("coreBase", () => {
  it("uses CORE_API_URL and strips a trailing slash", () => {
    vi.stubEnv("CORE_API_URL", "http://core-api:8000/");
    expect(coreBase()).toBe("http://core-api:8000");
  });
});

describe("proxyToCore", () => {
  it("attaches the bearer and passes upstream status + body through", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 201,
      text: async () => '{"ok":true}',
    } as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("CORE_API_URL", "http://core-api:8000");

    const res = await proxyToCore("/api/v1/proposals/commit", { method: "POST", token: "jwt123", body: "{}" });

    expect(res.status).toBe(201);
    expect(await res.text()).toBe('{"ok":true}');
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("http://core-api:8000/api/v1/proposals/commit");
    expect((init as RequestInit).method).toBe("POST");
    expect((init as { headers: Record<string, string> }).headers.authorization).toBe("Bearer jwt123");
  });

  it("turns an unreachable core-api into a clean 502", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));
    const res = await proxyToCore("/api/v1/schedule/slots", { token: "jwt" });
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ error: "core_api_unreachable" });
  });

  it("defaults to GET (no content-type) when there is no body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ status: 200, text: async () => "[]" } as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);
    await proxyToCore("/api/v1/schedule/slots", { token: "jwt" });
    const init = fetchMock.mock.calls[0]![1] as { method: string; headers: Record<string, string> };
    expect(init.method).toBe("GET");
    expect(init.headers["content-type"]).toBeUndefined();
  });
});
