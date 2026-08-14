import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import { ReportsPage } from "./ReportsPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, apiRequest: vi.fn() };
});

const overview = {
  generated_at: "2026-08-14T12:00:00Z", currency: "USD",
  current: { snapshot_date: "2026-08-14", currency: "USD", net_worth: "12000.0000", cash_available: "4000.0000", planned_income: "5000.0000", actual_income: "4500.0000", budgeted: "3000.0000", spent: "1400.0000", safe_to_spend: "2100.0000", planning_commitments: "400.0000", goal_reserves: "1000.0000", total_goal_target: "30000.0000", total_goal_current: "6000.0000", monthly_goal_contributions: "750.0000", total_debt: "8200.0000", planned_monthly_debt_payment: "500.0000", reserve_balance: "1500.0000", projected_30_day: "3000.0000", projected_60_day: "3500.0000", projected_90_day: "4200.0000", planned_debt_free_date: "2028-01-01", captured_at: "2026-08-14T12:00:00Z" },
  history: [],
};

describe("ReportsPage", () => {
  beforeEach(() => vi.mocked(apiRequest).mockResolvedValue(overview as never));
  it("renders the reporting foundation and current deterministic KPIs", async () => {
    render(<QueryClientProvider client={new QueryClient()}><ReportsPage /></QueryClientProvider>);
    expect(await screen.findByRole("heading", { name: "Reports" })).toBeInTheDocument();
    expect(await screen.findByText("Daily financial snapshots")).toBeInTheDocument();
    expect(screen.getByText("$12,000.00")).toBeInTheDocument();
    expect(screen.getByText("$8,200.00")).toBeInTheDocument();
    expect(screen.getByText("History starts with the first scheduled snapshot")).toBeInTheDocument();
  });
});
