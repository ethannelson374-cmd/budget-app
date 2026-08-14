import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import { ReportsPage } from "./ReportsPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, apiRequest: vi.fn() };
});

const range = { key: "6m", label: "Last 6 months", start: "2026-03-01", end: "2026-08-14", previous_start: "2025-09-01", previous_end: "2026-02-28", bucket: "month" };
const overview = {
  generated_at: "2026-08-14T12:00:00Z", currency: "USD",
  current: { snapshot_date: "2026-08-14", currency: "USD", net_worth: "12000.0000", cash_available: "4000.0000", planned_income: "5000.0000", actual_income: "4500.0000", budgeted: "3000.0000", spent: "1400.0000", safe_to_spend: "2100.0000", planning_commitments: "400.0000", goal_reserves: "1000.0000", total_goal_target: "30000.0000", total_goal_current: "6000.0000", monthly_goal_contributions: "750.0000", total_debt: "8200.0000", planned_monthly_debt_payment: "500.0000", reserve_balance: "1500.0000", projected_30_day: "3000.0000", projected_60_day: "3500.0000", projected_90_day: "4200.0000", planned_debt_free_date: "2028-01-01", captured_at: "2026-08-14T12:00:00Z" },
  history: [],
};
const spending = {
  generated_at: "2026-08-14T12:00:00Z", currency: "USD", range,
  summary: { income: "15000.0000", spending: "8200.0000", net_cash_flow: "6800.0000", savings_rate: "45.3333", spending_change_amount: "-400.0000", spending_change_pct: "-4.6512", income_change_pct: "2.0000", net_cash_flow_change_pct: "12.0000", current_month_spending: "1200.0000", projected_month_spending: "2861.5385" },
  series: [{ period: "2026-07", income: "5000.0000", spending: "2800.0000", net_cash_flow: "2200.0000" }, { period: "2026-08", income: "5000.0000", spending: "1200.0000", net_cash_flow: "3800.0000" }],
  categories: [{ category_id: 3, key: "groceries", name: "Groceries", amount: "1268.0000", previous_amount: "1100.0000", change_amount: "168.0000", change_pct: "15.2727", transaction_count: 12 }],
  top_merchants: [{ name: "Fresh Market", category: "Groceries", amount: "640.0000", transaction_count: 5 }],
  recurring: { recurring: "2200.0000", discretionary: "6000.0000", total: "8200.0000" },
};
const budget = {
  generated_at: "2026-08-14T12:00:00Z", currency: "USD", range, year: 2026, has_annual_plan: true,
  summary: { planned_income: "60000.0000", ytd_planned_income: "40000.0000", actual_income: "37800.0000", budgeted: "32400.0000", spent: "14500.0000", remaining: "17900.0000", unallocated: "27600.0000", income_variance: "-2200.0000", budget_utilization_pct: "44.7531", projected_year_end_spend: "23600.0000" },
  months: [{ month: "2026-08", source: "annual", planned_income: "5000.0000", actual_income: "4500.0000", budgeted: "2700.0000", spent: "1400.0000", remaining: "1300.0000", utilization_pct: "51.8519" }],
  categories: [{ category_id: 3, key: "groceries", name: "Groceries", planned_amount: "7200.0000", ytd_planned_amount: "4800.0000", spent_amount: "3600.0000", remaining_amount: "3600.0000", percent_used: "50.0000", ytd_variance: "1200.0000", annual_variance: "3600.0000" }],
};

function renderReports() {
  return render(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ReportsPage /></QueryClientProvider></MemoryRouter>);
}

describe("ReportsPage", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockImplementation(async (path) => {
      if (path.startsWith("/reports/spending")) return spending as never;
      if (path.startsWith("/reports/budget")) return budget as never;
      return overview as never;
    });
  });

  it("renders the reporting foundation and current deterministic KPIs", async () => {
    renderReports();
    expect(await screen.findByRole("heading", { name: "Reports" })).toBeInTheDocument();
    expect(await screen.findByText("Daily financial snapshots")).toBeInTheDocument();
    expect(screen.getByText("$12,000.00")).toBeInTheDocument();
    expect(screen.getByText("$8,200.00")).toBeInTheDocument();
    expect(screen.getByText("History starts with the first scheduled snapshot")).toBeInTheDocument();
  });

  it("switches to spending analytics and exposes transaction drill-through", async () => {
    const user = userEvent.setup();
    renderReports();
    await user.click(screen.getByRole("button", { name: "Spending" }));
    expect(await screen.findByRole("heading", { name: "Income vs spending" })).toBeInTheDocument();
    expect(screen.getByText("Where your money went")).toBeInTheDocument();
    expect(screen.getByText("Fresh Market")).toBeInTheDocument();
    const groceries = screen.getByRole("link", { name: /Groceries/ });
    expect(groceries).toHaveAttribute("href", expect.stringContaining("category_id=3"));
  });

  it("switches to annual budget performance", async () => {
    const user = userEvent.setup();
    renderReports();
    await user.click(screen.getByRole("button", { name: "Budget" }));
    expect(await screen.findByRole("heading", { name: "Budget vs actual" })).toBeInTheDocument();
    expect(screen.getByText("Annual budget utilization")).toBeInTheDocument();
    expect(screen.getByText("$32,400.00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Goals & Debt" })).toBeDisabled();
  });
});
