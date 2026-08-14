import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";

vi.mock("../api/queries", () => ({
  useSetupStatus: () => ({ isPending: false, isError: false, data: { initialized: true, demo_mode: false, bootstrap_required: false, google_auth_enabled: false, invite_only: true, email_delivery_configured: false }, refetch: vi.fn() }),
  useSetupOptions: () => ({ isPending: false, isError: false }),
  queryKeys: { setup: ["setup-status"] },
}));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ status: "anonymous", user: null, login: vi.fn(), verifyTwoFactor: vi.fn(), demoLogin: vi.fn(), logout: vi.fn(), refresh: vi.fn() }),
}));

describe("protected routing", () => {
  it("returns anonymous visitors to login without rendering financial data", async () => {
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={["/dashboard"]}><App /></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByRole("heading", { name: "Sign in to Budget" })).toBeInTheDocument();
    expect(screen.queryByText("Net worth")).not.toBeInTheDocument();
  });
});
