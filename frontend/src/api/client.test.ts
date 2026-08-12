import { afterEach, describe, expect, it, vi } from "vitest";
import { apiRequest, setCsrfToken } from "./client";
import type { ApiError } from "./client";

afterEach(() => setCsrfToken(null));

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
});
