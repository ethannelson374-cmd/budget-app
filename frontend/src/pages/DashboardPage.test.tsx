import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import type { DashboardData } from "../api/types";
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

describe("DashboardPage", () => {
  beforeEach(() => vi.mocked(apiRequest).mockReset().mockResolvedValue(dashboard));

  function renderDashboard() {
    return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><DashboardPage /></MemoryRouter></QueryClientProvider>);
  }

  it("renders summary arithmetic, excluded currencies, and honest empty states", async () => {
    renderDashboard();
    expect(await screen.findByText(/12,500/)).toBeInTheDocument();
    expect(screen.getByText(/Excluded: CAD/)).toBeInTheDocument();
    expect(screen.getByText("No cash flow activity in this period.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No transactions yet" })).toBeInTheDocument();
    expect(screen.getByText("37.5%")).toBeInTheDocument();
  });

  it("offers a working retry after a server failure", async () => {
    const user = userEvent.setup();
    vi.mocked(apiRequest).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(dashboard);
    renderDashboard();
    const retry = await screen.findByRole("button", { name: "Try again" });
    await user.click(retry);
    expect(await screen.findByText(/12,500/)).toBeInTheDocument();
    expect(apiRequest).toHaveBeenCalledTimes(2);
  });
});
