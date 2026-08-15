import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import { PlaidOAuthPage } from "./PlaidOAuthPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});

describe("PlaidOAuthPage", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.mocked(apiRequest).mockReset().mockImplementation(async () => ({
      configured: true,
      environment: "sandbox",
      connections: [],
    }));
  });

  it("resumes Link with the saved token and forwards duplicate-prevention metadata", async () => {
    window.sessionStorage.setItem("budget.plaid.link_token", "link-oauth-test");
    let options: PlaidLinkOptions | undefined;
    const handler: PlaidHandler = { open: vi.fn(), exit: vi.fn(), destroy: vi.fn() };
    window.Plaid = { create: vi.fn((value) => { options = value; return handler; }) };

    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/plaid/oauth?oauth_state_id=test"]}>
          <Routes>
            <Route path="/plaid/oauth" element={<PlaidOAuthPage />} />
            <Route path="/accounts" element={<div>Accounts restored</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(window.Plaid?.create).toHaveBeenCalled());
    expect(options?.token).toBe("link-oauth-test");
    expect(options?.receivedRedirectUri).toBe(window.location.href);
    options?.onLoad?.();
    expect(handler.open).toHaveBeenCalled();

    options?.onSuccess("public-oauth-test", {
      institution: { name: "First Platypus Bank", institution_id: "ins_109508" },
      accounts: [{ id: "acct-1", name: "Plaid Checking", mask: "1234" }],
    });

    await waitFor(() => expect(vi.mocked(apiRequest)).toHaveBeenCalledWith(
      "/plaid/exchange",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          public_token: "public-oauth-test",
          institution_id: "ins_109508",
          accounts: [{ name: "Plaid Checking", mask: "1234" }],
        }),
      }),
    ));
    expect(await screen.findByText("Accounts restored")).toBeInTheDocument();
    expect(window.sessionStorage.getItem("budget.plaid.link_token")).toBeNull();
  });
});

it("completes OAuth update mode without exchanging a new access token", async () => {
  window.sessionStorage.setItem("budget.plaid.link_session", JSON.stringify({ token: "link-update-oauth", mode: "update", connectionId: 11 }));
  let options: PlaidLinkOptions | undefined;
  const handler: PlaidHandler = { open: vi.fn(), exit: vi.fn(), destroy: vi.fn() };
  window.Plaid = { create: vi.fn((value) => { options = value; return handler; }) };

  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/plaid/oauth?oauth_state_id=update"]}>
        <Routes>
          <Route path="/plaid/oauth" element={<PlaidOAuthPage />} />
          <Route path="/accounts" element={<div>Updated account restored</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  await waitFor(() => expect(window.Plaid?.create).toHaveBeenCalled());
  expect(options?.token).toBe("link-update-oauth");
  options?.onSuccess(null, { institution: null, accounts: [] });
  await waitFor(() => expect(vi.mocked(apiRequest)).toHaveBeenCalledWith(
    "/plaid/connections/11/refresh",
    expect.objectContaining({ method: "POST" }),
  ));
  expect(await screen.findByText("Updated account restored")).toBeInTheDocument();
  expect(window.sessionStorage.getItem("budget.plaid.link_session")).toBeNull();
});
