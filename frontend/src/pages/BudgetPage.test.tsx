import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import type { AnnualBudgetPlan, CategorySelection, MonthlyBudgetView, YearBudgetView } from "../api/types";
import { BudgetPage } from "./BudgetPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    user: { settings: { annual_gross_income: "78000.0000" } },
  }),
}));

const categories: CategorySelection = {
  categories: [
    { id: 1, key: "income", name: "Income", group: "Income", enabled: true },
    { id: 2, key: "housing", name: "Housing", group: "Essentials", enabled: true },
    { id: 3, key: "groceries", name: "Groceries", group: "Essentials", enabled: true },
    { id: 4, key: "restaurants", name: "Restaurants", group: "Lifestyle", enabled: true },
    { id: 5, key: "transfers", name: "Transfers", group: "Financial", enabled: true },
  ],
};

const monthBudget: MonthlyBudgetView = {
  period: { month: "2026-08", start: "2026-08-01", end: "2026-08-31" },
  currency: "USD",
  source: "annual",
  monthly_mode: null,
  has_annual_plan: true,
  planned_income: "5000.0000",
  actual_income: "4500.0000",
  budgeted: "2100.0000",
  available_with_rollover: "2200.0000",
  spent: "1675.0000",
  remaining: "525.0000",
  unallocated: "2900.0000",
    cash_available: "6200.0000",
  upcoming_recurring: "300.0000",
  planning_commitments: "0.0000",
  goal_reserves: "0.0000",
  safe_to_spend: "5675.0000",
  notes: null,
  categories: [
    {
      category: categories.categories[1],
      base_amount: "1500.0000",
      rollover_amount: "0.0000",
      available_amount: "1500.0000",
      spent_amount: "1450.0000",
      remaining_amount: "50.0000",
      percent_used: "96.6667",
      status: "close",
      rollover_mode: "off",
    },
    {
      category: categories.categories[2],
      base_amount: "600.0000",
      rollover_amount: "100.0000",
      available_amount: "700.0000",
      spent_amount: "225.0000",
      remaining_amount: "475.0000",
      percent_used: "32.1429",
      status: "on_track",
      rollover_mode: "surplus",
    },
  ],
};

const annualPlan: AnnualBudgetPlan = {
  year: 2026,
  exists: true,
  planned_income: "60000.0000",
  notes: null,
  categories: [
    {
      category: categories.categories[1],
      annual_amount: "18000.0000",
      distribution: "even",
      monthly_amount: null,
      rollover_mode: "off",
      custom_months: [],
    },
    {
      category: categories.categories[2],
      annual_amount: "7200.0000",
      distribution: "monthly",
      monthly_amount: "600.0000",
      rollover_mode: "surplus",
      custom_months: [],
    },
  ],
};

const yearBudget: YearBudgetView = {
  year: 2026,
  currency: "USD",
  has_annual_plan: true,
  planned_income: "60000.0000",
  ytd_planned_income: "40000.0000",
  actual_income: "37800.0000",
  budgeted: "25200.0000",
  spent: "14500.0000",
  remaining: "10700.0000",
  unallocated: "34800.0000",
  categories: [
    {
      category: categories.categories[1],
      planned_amount: "18000.0000",
      ytd_planned_amount: "12000.0000",
      spent_amount: "11600.0000",
      remaining_amount: "6400.0000",
      percent_used: "64.4444",
    },
  ],
};

describe("BudgetPage", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset().mockImplementation((path) => {
      if (path === "/categories/selection") return Promise.resolve(categories as never);
      if (path.includes("/plan")) return Promise.resolve(annualPlan as never);
      if (path.includes("/budget/years/")) return Promise.resolve(yearBudget as never);
      return Promise.resolve(monthBudget as never);
    });
  });

  function renderBudget() {
    return render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><BudgetPage /></MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("shows monthly safe-to-spend and rollover-aware category progress", async () => {
    renderBudget();
    expect(await screen.findByText("Safe to spend")).toBeInTheDocument();
    expect(screen.getByText("$5,675.00")).toBeInTheDocument();
    expect(screen.getByText(/rollover.*100/)).toBeInTheDocument();
    expect(screen.getByText("Getting close")).toBeInTheDocument();
  });

  it("switches to annual planning and exposes the annual editor", async () => {
    const user = userEvent.setup();
    renderBudget();
    await screen.findByText("Safe to spend");
    await user.click(screen.getByRole("button", { name: "Year" }));
    expect(await screen.findByText("Annual planned income")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit annual plan" }));
    expect(await screen.findByRole("heading", { name: /budget goals/i })).toBeInTheDocument();
    expect(screen.getByDisplayValue("60,000.00")).toBeInTheDocument();
  });
});
