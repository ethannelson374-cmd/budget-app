import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import type { AdvisorStatus, CashFlowSankeyData, DashboardData, DashboardOnboarding, DashboardPreferences, InsightsResponse, MonthlyBudgetView } from "../api/types";
import { ToastProvider } from "../toast/ToastContext";
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


const preferences: DashboardPreferences = { preset: "everyday", onboarding_dismissed_at: null, cards: [
  { id: "net_worth", size: "compact", visible: true }, { id: "cash_available", size: "compact", visible: true }, { id: "income", size: "compact", visible: true }, { id: "spending", size: "compact", visible: true }, { id: "net_cash_flow", size: "compact", visible: true }, { id: "savings_rate", size: "compact", visible: true },
  { id: "cash_flow", size: "hero", visible: true }, { id: "top_spending", size: "standard", visible: true }, { id: "ask_budget", size: "hero", visible: true }, { id: "budget", size: "standard", visible: true }, { id: "insights", size: "hero", visible: true }, { id: "recent_transactions", size: "hero", visible: true }, { id: "accounts", size: "standard", visible: true }, { id: "data_freshness", size: "compact", visible: true }
] };
const onboarding: DashboardOnboarding = { tasks: [], completed: 0, total: 5, complete: false, dismissed: true, dismissed_at: "2026-08-14T12:00:00Z" };
const advisorStatus: AdvisorStatus = { available: true, enabled: true, store_history: true, provider: "gemini", model: "test" };

const cashFlow: CashFlowSankeyData = {
  period: { range: "month", label: "August 2026", start: "2026-08-01", end: "2026-08-31", previous_start: "2026-07-01", previous_end: "2026-07-31" },
  currency: "USD",
  summary: { income: "4000.0000", refunds: "0.0000", inflow: "4000.0000", spending: "2500.0000", net_cash_flow: "1500.0000", savings_rate: "37.5000", transaction_count: 6, excluded_transfer_count: 1 },
  nodes: [
    { id: "income:0", label: "Employer", kind: "income_source", amount: "4000.0000", transaction_count: 2, previous_amount: "3900.0000", change_percent: "2.5641", category_id: null, filters: { kind: "income", category_id: null, search: "Employer" } },
    { id: "cash-in", label: "Available cash", kind: "hub", amount: "4000.0000", transaction_count: 6, previous_amount: "3900.0000", change_percent: "2.5641", category_id: null, filters: null },
    { id: "category:housing", label: "Housing", kind: "expense", amount: "2000.0000", transaction_count: 1, previous_amount: "1900.0000", change_percent: "5.2632", category_id: 2, filters: { kind: "expense", category_id: 2, search: null } },
    { id: "retained-cash", label: "Retained cash", kind: "savings", amount: "1500.0000", transaction_count: 0, previous_amount: "1400.0000", change_percent: "7.1429", category_id: null, filters: null },
    { id: "category:groceries", label: "Groceries", kind: "expense", amount: "500.0000", transaction_count: 3, previous_amount: "600.0000", change_percent: "-16.6667", category_id: 3, filters: { kind: "expense", category_id: 3, search: null } },
  ],
  links: [
    { id: "income:0->cash-in", source: "income:0", target: "cash-in", label: "Employer", kind: "income", amount: "4000.0000", transaction_count: 2, share_percent: null, filters: { kind: "income", category_id: null, search: "Employer" } },
    { id: "cash-in->category:housing", source: "cash-in", target: "category:housing", label: "Housing", kind: "expense", amount: "2000.0000", transaction_count: 1, share_percent: "50.0000", filters: { kind: "expense", category_id: 2, search: null } },
    { id: "cash-in->retained-cash", source: "cash-in", target: "retained-cash", label: "Retained cash", kind: "savings", amount: "1500.0000", transaction_count: 0, share_percent: "37.5000", filters: null },
    { id: "cash-in->category:groceries", source: "cash-in", target: "category:groceries", label: "Groceries", kind: "expense", amount: "500.0000", transaction_count: 3, share_percent: "12.5000", filters: { kind: "expense", category_id: 3, search: null } },
  ],
};

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset().mockImplementation((path) => {
      if (path === "/insights/refresh") return Promise.resolve(insights as never);
      if (path.startsWith("/budget/")) return Promise.resolve(budget as never);
      if (path === "/dashboard/preferences") return Promise.resolve(preferences as never);
      if (path === "/dashboard/onboarding") return Promise.resolve(onboarding as never);
      if (path === "/advisor/status") return Promise.resolve(advisorStatus as never);
      if (path.startsWith("/cash-flow?")) return Promise.resolve(cashFlow as never);
      return Promise.resolve(dashboard as never);
    });
  });

  function renderDashboard() {
    return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ToastProvider><MemoryRouter><DashboardPage /></MemoryRouter></ToastProvider></QueryClientProvider>);
  }

  it("renders summary arithmetic, budget summary, excluded currencies, and honest empty states", async () => {
    renderDashboard();
    expect(await screen.findByText(/12,500/)).toBeInTheDocument();
    expect(screen.getByText(/Excluded: CAD/)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Cash flow map" })).toBeInTheDocument();
    expect(screen.getByText("Available cash")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No transactions yet" })).toBeInTheDocument();
    expect(screen.getAllByText("37.5%").length).toBeGreaterThan(0);
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
      if (path === "/dashboard/preferences") return Promise.resolve(preferences as never);
      if (path === "/dashboard/onboarding") return Promise.resolve(onboarding as never);
      if (path === "/advisor/status") return Promise.resolve(advisorStatus as never);
      if (path.startsWith("/cash-flow?")) return Promise.resolve(cashFlow as never);
      dashboardCalls += 1;
      return dashboardCalls === 1 ? Promise.reject(new Error("offline")) : Promise.resolve(dashboard as never);
    });
    renderDashboard();
    const retry = await screen.findByRole("button", { name: "Try again" });
    await user.click(retry);
    expect(await screen.findByText(/12,500/)).toBeInTheDocument();
  });
  it("renders the Sankey flow inspector and transaction drill-down", async () => {
    const user = userEvent.setup();
    renderDashboard();
    const housingFlow = await screen.findByRole("button", { name: /Housing: \$2,000/ });
    await user.click(housingFlow);
    const drillDown = await screen.findByRole("link", { name: "View transactions" });
    expect(drillDown.getAttribute("href")).toContain("category_id=2");
    expect(drillDown.getAttribute("href")).toContain("start_date=2026-08-01");
  });

  it("uses three snap sizes with a keyboard-accessible drag-resize grip", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await screen.findByText(/12,500/);
    await user.click(screen.getByRole("button", { name: "Customize" }));
    const grip = screen.getByRole("slider", { name: "Resize Net worth" });
    expect(grip).toHaveAttribute("aria-valuetext", "compact");
    grip.focus();
    await user.keyboard("{End}");
    expect(grip).toHaveAttribute("aria-valuetext", "hero");
    expect(grip.closest('[data-card-id="net_worth"]')).toHaveAttribute("data-card-size", "hero");
  });

});
