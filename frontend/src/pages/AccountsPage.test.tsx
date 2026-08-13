import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import { AccountsPage } from "./AccountsPage";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { settings: { currency: "USD" } } }),
}));
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});

describe("AccountsPage Plaid connection", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.mocked(apiRequest).mockReset().mockImplementation(async (path, init) => {
      if (path === "/accounts") return { accounts: [] };
      if (path === "/plaid/connections") return { configured: true, environment: "sandbox", connections: [] };
      if (path === "/plaid/link-token" && init?.method === "POST") return { link_token: "link-test", environment: "sandbox" };
      if (path === "/plaid/exchange" && init?.method === "POST") return { configured: true, environment: "sandbox", connections: [] };
      throw new Error(`Unexpected request: ${path}`);
    });
  });

  it("opens Link and exchanges the public token plus duplicate-prevention metadata", async () => {
    let options: PlaidLinkOptions | undefined;
    const handler: PlaidHandler = { open: vi.fn(), exit: vi.fn(), destroy: vi.fn() };
    window.Plaid = { create: vi.fn((value) => { options = value; return handler; }) };
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter><AccountsPage /></MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole("button", { name: "Connect a bank" }));
    await waitFor(() => expect(window.Plaid?.create).toHaveBeenCalled());
    expect(window.sessionStorage.getItem("budget.plaid.link_token")).toBe("link-test");
    options?.onLoad?.();
    expect(handler.open).toHaveBeenCalled();
    options?.onSuccess("public-test", {
      institution: { name: "First Platypus Bank", institution_id: "ins_109508" },
      accounts: [{ id: "plaid-checking", name: "Plaid Checking", mask: "1234" }],
    });
    await waitFor(() => expect(vi.mocked(apiRequest)).toHaveBeenCalledWith(
      "/plaid/exchange",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          public_token: "public-test",
          institution_id: "ins_109508",
          accounts: [{ name: "Plaid Checking", mask: "1234" }],
        }),
      }),
    ));
    expect(handler.destroy).toHaveBeenCalled();
  });
});

it("syncs a connected Plaid institution on demand", async () => {
  vi.mocked(apiRequest).mockReset().mockImplementation(async (path, init) => {
    if (path === "/accounts") return { accounts: [] };
    if (path === "/plaid/connections") return {
      configured: true,
      environment: "sandbox",
      connections: [{
        id: 7,
        status: "active",
        last_error_code: null,
        last_synced_at: "2026-08-13T06:00:00Z",
        transactions_update_status: null,
        transactions_last_synced_at: null,
        transactions_last_error_code: null,
        institution: { id: 1, name: "First Platypus Bank", logo: null, primary_color: null, url: null },
        accounts: [],
      }],
    };
    if (path === "/plaid/connections/7/sync" && init?.method === "POST") return {
      connection_id: 7,
      added: 12,
      modified: 2,
      removed: 1,
      update_status: "HISTORICAL_UPDATE_COMPLETE",
      last_synced_at: "2026-08-13T06:05:00Z",
    };
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><AccountsPage /></MemoryRouter>
    </QueryClientProvider>,
  );

  await user.click(await screen.findByRole("button", { name: "Sync now" }));
  await waitFor(() => expect(vi.mocked(apiRequest)).toHaveBeenCalledWith(
    "/plaid/connections/7/sync",
    expect.objectContaining({ method: "POST" }),
  ));
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Transaction sync complete: 12 added, 2 updated, 1 removed.",
  );
});
