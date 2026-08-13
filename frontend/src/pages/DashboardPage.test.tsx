import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import type { DashboardData, InsightsResponse, MonthlyBudgetView } from "../api/types";
import { DashboardPage } from "./DashboardPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});

const dashboard: DashboardData = {
  period: { month: "2026-08", start: "2026-08-01", end: "2026-08-31" },
  currency: "USD",
  as_of: "2026-08-12T12:00:00Z",
  summary: { net_worth: "12500.0000", cash_available: "5000.0000", income: "4000.0000", spending: "2500.0000", net_cash_flow: "1500.0000", savings_rate: "37.5000" },
  spending_by_category: [],
  daily_cash_flow: [],
  accounts: [],
  recent_transactions: [],
  excluded_currencies: ["CAD"],
};

const insights: InsightsResponse = {
  generated_at: "2026-08-13T12:00:00Z",
  active_count: 1,
  dismissed_count: 0,
  resolved_count: 0,
  insights: [{
    id: 1,
    signal_type: "category_overspend",
    category: "budget",
    priority: "important",
    score: 80,
    status: "active",
    title: "Restaurants spending is over budget",
    summary: "Dining is above plan this month.",
    recommendation: "Keep restaurant spending lower for the rest of the month.",
    evidence: [],
    action_route: "/budget",
    first_seen_at: "2026-08-13T12:00:00Z",
    last_seen_at: "2026-08-13T12:00:00Z",
    dismissed_at: null,
    resolved_at: null,
  }],
};

const budget: MonthlyBudgetView = {
  period: { month: "2026-08", start: "2026-08-01", end: "2026-08-31" },
  currency: "USD",
  source: "annual",
  monthly_mode: null,
  has_annual_plan: true,
  planned_income: "5000.0000",
  actual_income: "4000.0000",
  budgeted: "3000.0000",
  planning_commitments: "0.0000",
  goal_reserves: "0.0000",
  available_with_rollover: "3100.0000",
  spent: "2500.0000",
  remaining: "600.0000",
  unallocated: "2000.0000",
  cash_available: "5000.0000",
  upcoming_recurring: "350.0000",
  safe_to_spend: "4400.0000",
  notes: null,
  categories: [],
};

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset().mockImplementation((path) => {
      if (path === "/insights/refresh") return Promise.resolve(insights as never);
      if (path.startsWith("/budget/")) return Promise.resolve(budget as never);
      return Promise.resolve(dashboard as never);
    });
  });

  function renderDashboard() {
    return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><DashboardPage /></MemoryRouter></QueryClientProvider>);
  }

  it("renders summary arithmetic, budget summary, excluded currencies, and honest empty states", async () => {
    renderDashboard();
    expect(await screen.findByText(/12,500/)).toBeInTheDocument();
    expect(screen.getByText(/Excluded: CAD/)).toBeInTheDocument();
    expect(screen.getByText("No cash flow activity in this period.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No transactions yet" })).toBeInTheDocument();
    expect(screen.getByText("37.5%")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open budget/ })).toBeInTheDocument();
    expect(screen.getByText("$4,400.00")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Restaurants spending is over budget" })).toBeInTheDocument();
  });

  it("offers a working retry after a dashboard server failure", async () => {
    const user = userEvent.setup();
    let dashboardCalls = 0;
    vi.mocked(apiRequest).mockImplementation((path) => {
      if (path === "/insights/refresh") return Promise.resolve(insights as never);
      if (path.startsWith("/budget/")) return Promise.resolve(budget as never);
      dashboardCalls += 1;
      return dashboardCalls === 1 ? Promise.reject(new Error("offline")) : Promise.resolve(dashboard as never);
    });
    renderDashboard();
    const retry = await screen.findByRole("button", { name: "Try again" });
    await user.click(retry);
    expect(await screen.findByText(/12,500/)).toBeInTheDocument();
  });
});
