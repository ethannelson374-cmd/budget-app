import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import type { FinancialCalendarView } from "../api/types";
import { RecurringPage } from "./RecurringPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});

const calendar: FinancialCalendarView = {
  generated_at: "2026-08-16T12:00:00-05:00",
  currency: "USD",
  period: { month: "2026-08", start: "2026-08-01", end: "2026-08-31", today: "2026-08-16", label: "August 2026", projection_available: true, projection_start: "2026-08-16" },
  summary: { cash_available_now: "2200.0000", projected_month_start: "2200.0000", expected_inflow: "2250.0000", expected_outflow: "1024.9900", projected_month_end: "3425.0100", lowest_projected_balance: "1875.0100", lowest_balance_date: "2026-08-22", reserve_balance: "1000.0000", status: "healthy", observed_events: 1, expected_events: 3 },
  recurring: { detected_streams: 3, monthly_inflow_estimate: "4500.0000", monthly_outflow_estimate: "1024.9900" },
  events: [
    { id: "transaction:1", date: "2026-08-12", name: "StreamBox", kind: "subscription", status: "observed", amount: "24.9900", impact: "-24.9900", cadence: null, price_change_pct: null, stream_id: null, transaction_id: 1, account: { id: 1, name: "Checking", currency: "USD" }, category: { id: 8, key: "subscriptions", name: "Subscriptions" }, source_detail: "Posted recurring activity", filters: { start_date: "2026-08-12", end_date: "2026-08-12", account_id: 1, category_id: 8, kind: "expense", search: "StreamBox" }, ask_prompt: "Explain StreamBox" },
    { id: "stream:2:2026-08-20:0", date: "2026-08-20", name: "Northstar Software", kind: "income", status: "expected", amount: "2250.0000", impact: "2250.0000", cadence: "biweekly", price_change_pct: "0.0000", stream_id: 2, transaction_id: null, account: { id: 1, name: "Checking", currency: "USD" }, category: { id: 1, key: "income", name: "Income" }, source_detail: "Detected biweekly pattern", filters: { start_date: null, end_date: null, account_id: 1, category_id: 1, kind: "income", search: "Northstar Software" }, ask_prompt: "Explain paycheck" },
    { id: "debt:1:2026-08-22", date: "2026-08-22", name: "Auto loan", kind: "debt", status: "planned", amount: "700.0000", impact: "-700.0000", cadence: "monthly", price_change_pct: null, stream_id: null, transaction_id: null, account: null, category: null, source_detail: "Planned debt payment", filters: { start_date: null, end_date: null, account_id: null, category_id: null, kind: "expense", search: null }, ask_prompt: "Explain auto loan" },
    { id: "stream:3:2026-08-24:0", date: "2026-08-24", name: "Electric", kind: "expense", status: "expected", amount: "324.9900", impact: "-324.9900", cadence: "monthly", price_change_pct: null, stream_id: 3, transaction_id: null, account: { id: 1, name: "Checking", currency: "USD" }, category: null, source_detail: "Detected monthly pattern", filters: { start_date: null, end_date: null, account_id: 1, category_id: null, kind: "expense", search: "Electric" }, ask_prompt: "Explain electric" },
  ],
  projection: [
    { date: "2026-08-16", balance: "2200.0000", delta: "0.0000", event_count: 0, below_reserve: false },
    { date: "2026-08-20", balance: "4450.0000", delta: "2250.0000", event_count: 1, below_reserve: false },
    { date: "2026-08-22", balance: "3750.0000", delta: "-700.0000", event_count: 1, below_reserve: false },
    { date: "2026-08-24", balance: "3425.0100", delta: "-324.9900", event_count: 1, below_reserve: false },
  ],
};

describe("RecurringPage financial calendar", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset().mockImplementation(async (path: string) => {
      if (path.startsWith("/financial-calendar")) return calendar as never;
      return { currency: "USD", streams: [], monthly_outflow_estimate: "0", monthly_inflow_estimate: "0" } as never;
    });
  });

  function renderPage() {
    return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><RecurringPage /></MemoryRouter></QueryClientProvider>);
  }

  it("renders the projected cash ribbon, timeline, recurring baseline, and event drill-down", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "Financial calendar" })).toBeInTheDocument();
    expect(await screen.findByText("Projected month end")).toBeInTheDocument();
    expect(await screen.findByText("Northstar Software")).toBeInTheDocument();
    expect(await screen.findByText("Recurring baseline")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ask Budget" })).toHaveAttribute("href", "/advisor");
    expect(screen.getByRole("link", { name: "View activity" }).getAttribute("href")).toContain("search=StreamBox");
  });

  it("switches to the spatial calendar view", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Northstar Software");
    await user.click(screen.getByRole("button", { name: "Calendar" }));
    expect(screen.getByRole("grid", { name: "August 2026 financial calendar" })).toBeInTheDocument();
    expect(screen.getByText("Auto loan")).toBeInTheDocument();
  });
});
