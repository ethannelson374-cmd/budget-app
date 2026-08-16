import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import axe from "axe-core";
import { ApiError, apiRequest } from "../api/client";
import type { AuthSession, SetupOptions } from "../api/types";
import { SetupWizard } from "./SetupPage";

const establishSession = vi.fn();
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ establishSession }) }));
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ ApiError: typeof ApiError; apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});

const options: SetupOptions = {
  currencies: [{ code: "USD", name: "US Dollar" }],
  pay_frequencies: [{ value: "monthly", label: "Monthly" }],
  default_categories: [{ key: "other", name: "Other", group: "Other", selected_by_default: true }],
};

async function completeWizard(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Username"), "owner");
  await user.type(screen.getByLabelText("Email address"), "owner@example.test");
  await user.type(screen.getByLabelText(/^Password/), "not-stored-password");
  await user.type(screen.getByLabelText("Confirm password"), "not-stored-password");
  await user.type(screen.getByLabelText(/^Bootstrap token/), "not-stored-bootstrap-token");
  await user.click(screen.getByRole("button", { name: /Continue/ }));
  await user.click(screen.getByRole("button", { name: /Continue/ }));
  await user.click(screen.getByRole("button", { name: "Finish setup" }));
}

describe("SetupWizard secret handling", () => {
  beforeEach(() => {
    establishSession.mockClear();
    vi.mocked(apiRequest).mockReset();
  });

  it("clears password and bootstrap token and never puts them in Query or browser storage", async () => {
    vi.mocked(apiRequest).mockRejectedValue(new ApiError("Bootstrap token was rejected.", { status: 403 }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter><SetupWizard options={options} bootstrapRequired /></MemoryRouter>
      </QueryClientProvider>,
    );

    await completeWizard(user);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Bootstrap token was rejected."));
    expect(apiRequest).toHaveBeenCalledWith("/setup", expect.objectContaining({
      method: "POST",
      headers: { "X-Bootstrap-Token": "not-stored-bootstrap-token" },
      body: expect.stringContaining('"password":"not-stored-password"'),
    }));
    expect(screen.getByLabelText(/^Password/)).toHaveValue("");
    expect(screen.getByLabelText("Confirm password")).toHaveValue("");
    expect(screen.getByLabelText(/^Bootstrap token/)).toHaveValue("");
    expect(client.getMutationCache().getAll()).toHaveLength(0);
    expect(JSON.stringify(client.getQueryCache().getAll())).not.toContain("not-stored");
    expect(JSON.stringify(localStorage)).not.toContain("not-stored");
    expect(JSON.stringify(sessionStorage)).not.toContain("not-stored");
  });

  it("establishes authentication from the committed setup response without a second request", async () => {
    const session: AuthSession = {
      user: {
        id: 1,
        username: "owner",
        email: "owner@example.test",
        is_admin: true,
        email_verified: true,
        settings: { currency: "USD", timezone: "UTC", theme: "system", annual_gross_income: null, pay_frequency: null, advisor_enabled: true, advisor_share_merchants: false, advisor_share_planning_names: false, advisor_include_descriptions: false, advisor_store_history: true },
      },
      csrf_token: "returned-csrf",
    };
    vi.mocked(apiRequest).mockResolvedValue(session);
    const client = new QueryClient();
    client.setQueryData(["setup-status"], { initialized: false, demo_mode: false, bootstrap_required: true, google_auth_enabled: false, invite_only: true, email_delivery_configured: false });
    const user = userEvent.setup();
    render(<QueryClientProvider client={client}><MemoryRouter><SetupWizard options={options} bootstrapRequired /></MemoryRouter></QueryClientProvider>);

    await completeWizard(user);

    await waitFor(() => expect(establishSession).toHaveBeenCalledWith(session));
    expect(apiRequest).toHaveBeenCalledTimes(1);
    expect(client.getQueryData(["setup-status"])).toEqual({ initialized: true, demo_mode: false, bootstrap_required: false, google_auth_enabled: false, invite_only: true, email_delivery_configured: false });
  });

  it("has no serious automated accessibility violations", async () => {
    const client = new QueryClient();
    const { container } = render(<QueryClientProvider client={client}><MemoryRouter><SetupWizard options={options} bootstrapRequired /></MemoryRouter></QueryClientProvider>);
    const result = await axe.run(container);
    expect(result.violations.filter((violation) => ["critical", "serious"].includes(violation.impact ?? ""))).toEqual([]);
  });
});
