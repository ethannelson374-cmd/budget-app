import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import type { TrendsView } from "../api/types";
import { TrendsPage } from "./TrendsPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});

const data: TrendsView = {
  generated_at: "2026-08-16T12:00:00Z",
  currency: "USD",
  period: { range: "6m", label: "Last 6 months", start: "2026-03-01", end: "2026-08-16", previous_start: "2025-09-14", previous_end: "2026-02-28", bucket: "month" },
  summary: { net_worth: "7210.2800", assets: "16090.5200", liabilities: "8880.2400", cash_available: "15940.5200", change_amount: "2710.2800", change_percent: "60.2284", ytd_change_amount: "3000.0000", ytd_change_percent: "71.2589", average_monthly_income: "4500.0000", income_variability_percent: "0.0000" },
  net_worth_history: [
    { date: "2026-03-01", net_worth: "4500.0000", cash_available: "14300.0000", total_debt: "9800.0000", assets: null, liabilities: null },
    { date: "2026-06-01", net_worth: "6150.0000", cash_available: "15400.0000", total_debt: "9250.0000", assets: null, liabilities: null },
    { date: "2026-08-16", net_worth: "7210.2800", cash_available: "15940.5200", total_debt: "8880.2400", assets: "16090.5200", liabilities: "8880.2400" },
  ],
  balance_history: [{ date: "2026-08-16", assets: "16090.5200", liabilities: "8880.2400", net_worth: "7210.2800" }],
  composition: [
    { key: "cash", label: "Cash & savings", kind: "asset", value: "16090.5200", share_percent: "64.4400", account_count: 2 },
    { key: "liabilities", label: "Credit & loans", kind: "liability", value: "8880.2400", share_percent: "35.5600", account_count: 2 },
  ],
  account_contributions: [
    { account_id: 1, name: "Everyday Checking", institution: "Demo Credit Union", account_type: "depository", current_balance: "3240.5200", start_balance: "2800.0000", change_amount: "440.5200", change_percent: "15.7329", history_available: true, history_start_date: "2026-03-01" },
  ],
  cash_flow: [
    { period: "2026-07", income: "4500.0000", spending: "2900.0000", net_cash_flow: "1600.0000", savings_rate: "35.5556" },
    { period: "2026-08", income: "4500.0000", spending: "1778.3500", net_cash_flow: "2721.6500", savings_rate: "60.4811" },
  ],
  spending_categories: [
    { key: "housing", label: "Housing", category_id: 2, current: "1450.0000", previous: "1450.0000", change_amount: "0.0000", change_percent: "0.0000", share_percent: "81.5360" },
  ],
  income_sources: [
    { label: "Northstar Software", current: "4500.0000", previous: "4500.0000", change_amount: "0.0000", change_percent: "0.0000", share_percent: "100.0000" },
  ],
  history: { financial_snapshot_start: "2026-03-01", account_snapshot_start: "2026-03-01", account_snapshot_days: 6, account_tracking_active: true },
};

describe("TrendsPage", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset().mockResolvedValue(data as never);
  });

  function renderPage() {
    return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><TrendsPage /></MemoryRouter></QueryClientProvider>);
  }

  it("renders financial terrain, composition, account momentum, and drill-downs", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "Net worth history" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Mar 1, 2026 net worth/ })).toBeInTheDocument();
    expect(screen.getByText("Cash & savings")).toBeInTheDocument();
    expect(screen.getByText("Everyday Checking")).toBeInTheDocument();
    expect(screen.getByText("Northstar Software")).toBeInTheDocument();
    const activity = screen.getByRole("link", { name: /Activity/ });
    expect(activity.getAttribute("href")).toContain("account_id=1");
  });

  it("switches trend ranges and requests the selected period", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Net worth history" });
    await user.click(screen.getByRole("button", { name: "1Y" }));
    expect(vi.mocked(apiRequest)).toHaveBeenCalledWith("/trends?range=1y");
  });
});
