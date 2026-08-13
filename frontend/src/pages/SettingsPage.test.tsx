import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import { SettingsPage } from "./SettingsPage";

const setPreference = vi.fn();
let sessionIsCurrent = true;
const isSessionCurrent = vi.fn(() => sessionIsCurrent);
vi.mock("../theme/ThemeContext", () => ({ useTheme: () => ({ setPreference }) }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ sessionGeneration: 1, isSessionCurrent }) }));
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});

const settings = { currency: "USD", timezone: "UTC", theme: "system", annual_gross_income: null, pay_frequency: null };
const categories = { categories: [
  { id: 1, key: "groceries", name: "Groceries", group: "Everyday", enabled: true },
  { id: 2, key: "other", name: "Other", group: "Other", enabled: true },
] };
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
      throw new Error(`Unexpected request: ${path}`);
    });
  });

  it("updates preferences and category selection through CSRF-protected API mutations", async () => {
    const user = userEvent.setup();
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>);
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
      throw new Error(`Unexpected request: ${path}`);
    });
    const client = new QueryClient();
    const user = userEvent.setup();
    render(<QueryClientProvider client={client}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>);
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
