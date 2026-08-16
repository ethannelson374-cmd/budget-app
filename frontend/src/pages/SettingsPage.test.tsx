import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../toast/ToastContext";
import { apiRequest } from "../api/client";
import { SettingsPage } from "./SettingsPage";

const setPreference = vi.fn();
let sessionIsCurrent = true;
const isSessionCurrent = vi.fn(() => sessionIsCurrent);
vi.mock("../theme/ThemeContext", () => ({ useTheme: () => ({ setPreference }) }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ sessionGeneration: 1, isSessionCurrent, user: { id: 1, username: "owner", email: "owner@example.test", is_admin: false, email_verified: true }, refresh: vi.fn() }) }));
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});

const settings = { currency: "USD", timezone: "UTC", theme: "system", annual_gross_income: null, pay_frequency: null, advisor_enabled: true, advisor_share_merchants: false, advisor_share_planning_names: false, advisor_include_descriptions: false, advisor_store_history: true };
const categories = { categories: [
  { id: 1, key: "groceries", name: "Groceries", group: "Everyday", enabled: true },
  { id: 2, key: "other", name: "Other", group: "Other", enabled: true },
] };
const advisorStatus = { available: true, enabled: true, store_history: true, provider: "openai", model: "gpt-5.6" };
const options = { currencies: [{ code: "USD", name: "US Dollar" }], pay_frequencies: [{ value: "monthly", label: "Monthly" }], default_categories: [] };

describe("SettingsPage", () => {
  beforeEach(() => {
    setPreference.mockClear();
    sessionIsCurrent = true;
    isSessionCurrent.mockClear();
    vi.mocked(apiRequest).mockReset().mockImplementation(async (path, init) => {
      if (path === "/settings" && init?.method === "PATCH") return JSON.parse(String(init.body));
      if (path === "/settings") return settings;
      if (path === "/categories/selection" && init?.method === "PUT") {
        const selected = JSON.parse(String(init.body)).category_keys as string[];
        return { categories: categories.categories.map((category) => ({ ...category, enabled: selected.includes(category.key) })) };
      }
      if (path === "/categories/selection") return categories;
      if (path === "/setup/options") return options;
      if (path === "/transaction-rules") return { rules: [] };
      if (path === "/advisor/status") return advisorStatus;
      if (path === "/accounts") return { accounts: [] };
      if (path === "/auth/security") return { is_admin: false, email_verified: true, has_password: true, google_enabled: false, google_connected: false, two_factor_enabled: false, email_delivery_configured: false, invite_only: true };
      if (path === "/auth/sessions") return { sessions: [] };
      if (path === "/notifications/preferences") return { in_app_enabled: true, email_enabled: false, email_delivery_available: false, spending_alerts: true, forecast_alerts: true, goal_milestones: true, recurring_changes: true, large_transaction_alerts: false, large_transaction_threshold: "250.0000", weekly_summary: true, monthly_summary: true };
      if (path === "/advisor/conversations" && init?.method === "DELETE") return { ok: true };
      throw new Error(`Unexpected request: ${path}`);
    });
  });

  it("updates preferences and category selection through CSRF-protected API mutations", async () => {
    const user = userEvent.setup();
    render(<QueryClientProvider client={new QueryClient()}><ToastProvider><MemoryRouter><SettingsPage /></MemoryRouter></ToastProvider></QueryClientProvider>);
    await screen.findByRole("heading", { name: "Financial preferences" });
    await user.click(screen.getByRole("radio", { name: "Dark" }));
    await user.click(screen.getByRole("button", { name: "Save preferences" }));
    await waitFor(() => expect(vi.mocked(apiRequest)).toHaveBeenCalledWith("/settings", expect.objectContaining({ method: "PATCH", body: expect.stringContaining('"theme":"dark"') })));
    expect(setPreference).toHaveBeenCalledWith("dark");

    await user.click(screen.getByRole("checkbox", { name: /Groceries/ }));
    await user.click(screen.getByRole("button", { name: "Save categories" }));
    await waitFor(() => expect(vi.mocked(apiRequest)).toHaveBeenCalledWith("/categories/selection", expect.objectContaining({ method: "PUT", body: JSON.stringify({ category_keys: ["other"] }) })));
  });

  it("ignores a mutation response that arrives after the authentication generation changes", async () => {
    let resolvePatch!: (value: typeof settings) => void;
    const delayedPatch = new Promise<typeof settings>((resolve) => { resolvePatch = resolve; });
    vi.mocked(apiRequest).mockImplementation(async (path, init) => {
      if (path === "/settings" && init?.method === "PATCH") return delayedPatch;
      if (path === "/settings") return settings;
      if (path === "/categories/selection") return categories;
      if (path === "/setup/options") return options;
      if (path === "/transaction-rules") return { rules: [] };
      if (path === "/advisor/status") return advisorStatus;
      if (path === "/accounts") return { accounts: [] };
      if (path === "/auth/security") return { is_admin: false, email_verified: true, has_password: true, google_enabled: false, google_connected: false, two_factor_enabled: false, email_delivery_configured: false, invite_only: true };
      if (path === "/auth/sessions") return { sessions: [] };
      if (path === "/notifications/preferences") return { in_app_enabled: true, email_enabled: false, email_delivery_available: false, spending_alerts: true, forecast_alerts: true, goal_milestones: true, recurring_changes: true, large_transaction_alerts: false, large_transaction_threshold: "250.0000", weekly_summary: true, monthly_summary: true };
      if (path === "/advisor/conversations" && init?.method === "DELETE") return { ok: true };
      throw new Error(`Unexpected request: ${path}`);
    });
    const client = new QueryClient();
    const user = userEvent.setup();
    render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter><SettingsPage /></MemoryRouter></ToastProvider></QueryClientProvider>);
    await screen.findByRole("heading", { name: "Financial preferences" });
    await user.click(screen.getByRole("radio", { name: "Dark" }));
    await user.click(screen.getByRole("button", { name: "Save preferences" }));
    sessionIsCurrent = false;
    resolvePatch({ ...settings, theme: "dark" });

    await waitFor(() => expect(isSessionCurrent).toHaveBeenCalledWith(1));
    expect(setPreference).not.toHaveBeenCalledWith("dark");
    expect(client.getQueryData(["settings"])).toEqual(settings);
    expect(screen.queryByText("Preferences saved.")).not.toBeInTheDocument();
  });
});
