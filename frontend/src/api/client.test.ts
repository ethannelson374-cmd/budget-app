import { afterEach, describe, expect, it, vi } from "vitest";
import { apiEventStream, apiRequest, setCsrfToken } from "./client";
import type { ApiError } from "./client";

afterEach(() => { setCsrfToken(null); vi.restoreAllMocks(); });

describe("apiRequest", () => {
  it("uses same-origin credentials and adds CSRF only to unsafe requests", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "content-type": "application/json" } }),
    );
    setCsrfToken("memory-only-csrf");

    await apiRequest("/settings");
    await apiRequest("/settings", { method: "PATCH", body: JSON.stringify({ theme: "dark" }) });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/v1/settings", expect.objectContaining({ credentials: "include", cache: "no-store" }));
    const getHeaders = fetchMock.mock.calls[0][1]?.headers as Headers;
    const patchHeaders = fetchMock.mock.calls[1][1]?.headers as Headers;
    expect(getHeaders.has("X-CSRF-Token")).toBe(false);
    expect(patchHeaders.get("X-CSRF-Token")).toBe("memory-only-csrf");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("maps the stable API error envelope without exposing response internals", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "invalid_login", message: "Sign-in failed", request_id: "request-123" } }), {
        status: 401,
        headers: { "content-type": "application/json" },
      }),
    );
    const expectedError: Partial<ApiError> = {
      status: 401,
      code: "invalid_login",
      message: "Sign-in failed",
      requestId: "request-123",
    };
    await expect(apiRequest("/auth/login", { method: "POST", body: "{}" })).rejects.toMatchObject(expectedError);
  });
  it("parses SSE events and preserves Retry-After errors", async () => {
    setCsrfToken("csrf");
    const encoder = new TextEncoder();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(new ReadableStream({ start(controller) { controller.enqueue(encoder.encode('event: delta\ndata: {"text":"Hi"}\n\n')); controller.enqueue(encoder.encode('event: done\ndata: {"answer":"Hi"}\n\n')); controller.close(); } }), { status: 200, headers: { "content-type": "text/event-stream" } }));
    const events: string[] = [];
    await apiEventStream("/advisor/conversations/1/messages/stream", { method: "POST", body: "{}" }, ({ event }) => events.push(event));
    expect(events).toEqual(["delta", "done"]);

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: "advisor_rate_limited", message: "Slow down" } }), { status: 429, headers: { "content-type": "application/json", "retry-after": "12" } }));
    await expect(apiEventStream("/advisor/conversations/1/messages/stream", { method: "POST", body: "{}" }, () => undefined)).rejects.toMatchObject({ status: 429, retryAfter: 12 });
  });
});
