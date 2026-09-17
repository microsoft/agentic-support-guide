import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "../api/client";

function mockFetch(impl: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  const spy = vi.fn(impl);
  vi.stubGlobal("fetch", spy);
  return spy;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("prefixes every path with the API base", async () => {
    const fetchSpy = mockFetch(() => jsonResponse({ status: "ok" }));
    await api.health();
    expect(fetchSpy).toHaveBeenCalledWith("/api/health", expect.anything());
  });

  it("omits the query string when no assessment filters are set", async () => {
    const fetchSpy = mockFetch(() => jsonResponse({}));
    await api.scoresSummary({});
    expect(fetchSpy.mock.calls[0][0]).toBe("/api/scores/summary");
  });

  it("encodes only the assessment filters that have values", async () => {
    const fetchSpy = mockFetch(() => jsonResponse({}));
    await api.scoresSummary({ region: "REG-001", segment: "", process_area: "lead-response" });
    expect(fetchSpy.mock.calls[0][0]).toBe(
      "/api/scores/summary?region=REG-001&process_area=lead-response",
    );
  });

  it("escapes filter values that need encoding", async () => {
    const fetchSpy = mockFetch(() => jsonResponse({}));
    await api.scoresSummary({ segment: "segment a&b" });
    expect(fetchSpy.mock.calls[0][0]).toBe("/api/scores/summary?segment=segment+a%26b");
  });

  it("posts the recommendation body as JSON", async () => {
    const fetchSpy = mockFetch(() => jsonResponse({ status: "ok" }));
    const body = {
      dealership_id: "DLR-0001",
      category: "lead-response",
      concern_text: "synthetic concern",
      dealer_group_id: "GROUP-A",
    };
    await api.recommendation(body);
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual(body);
    expect((init.headers as Record<string, string>)["content-type"]).toBe("application/json");
  });

  it("raises ApiError carrying the HTTP status on a non-2xx response", async () => {
    mockFetch(() => jsonResponse({ detail: "nope" }, 403));
    await expect(api.demoReset()).rejects.toMatchObject({
      name: "ApiError",
      status: 403,
    });
  });

  it("raises ApiError with status 0 on a network failure", async () => {
    mockFetch(() => {
      throw new Error("connection refused");
    });
    const err = await api.health().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(0);
    expect((err as ApiError).message).toContain("connection refused");
  });
});
