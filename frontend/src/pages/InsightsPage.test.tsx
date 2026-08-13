import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import type { InsightsResponse } from "../api/types";
import { InsightsPage } from "./InsightsPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});

const response: InsightsResponse = {
  generated_at: "2026-08-13T12:00:00Z",
  active_count: 1,
  dismissed_count: 0,
  resolved_count: 0,
  insights: [{
    id: 7,
    signal_type: "forecast_reserve_risk",
    category: "forecast",
    priority: "critical",
    score: 96,
    status: "active",
    title: "Your 30-day forecast falls below your reserve",
    summary: "Projected cash falls below the reserve.",
    recommendation: "Test a scenario before the shortfall arrives.",
    evidence: [{ label: "Below reserve", value: "USD 200.00", detail: null }],
    action_route: "/plan",
    first_seen_at: "2026-08-13T12:00:00Z",
    last_seen_at: "2026-08-13T12:00:00Z",
    dismissed_at: null,
    resolved_at: null,
  }],
};

describe("InsightsPage", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset().mockImplementation((path, init) => {
      if (path === "/insights/refresh" && init?.method === "POST") return Promise.resolve(response as never);
      if (path === "/insights/7" && init?.method === "PATCH") return Promise.resolve({ ...response.insights[0], status: "dismissed" } as never);
      if (path.startsWith("/insights?status=")) return Promise.resolve({ ...response, insights: [] } as never);
      throw new Error(`Unexpected request: ${path}`);
    });
  });

  it("renders deterministic insight evidence and allows dismissal", async () => {
    const user = userEvent.setup();
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><InsightsPage /></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByRole("heading", { name: "Your 30-day forecast falls below your reserve" })).toBeInTheDocument();
    expect(screen.getByText("USD 200.00")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(vi.mocked(apiRequest)).toHaveBeenCalledWith(
      "/insights/7",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ status: "dismissed" }) }),
    );
  });
});
