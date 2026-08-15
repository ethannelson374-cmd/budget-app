import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import { ToastProvider } from "../toast/ToastContext";
import { NotificationsPage } from "./NotificationsPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});

describe("NotificationsPage", () => {
  it("renders unread alerts and marks them read", async () => {
    vi.mocked(apiRequest).mockImplementation(async (path, init) => {
      if (path === "/notifications?status=all&limit=100") return { unread_count: 1, notifications: [{ id: 7, type: "forecast_reserve_risk", severity: "critical", title: "Cash forecast needs attention", body: "Projected cash falls below reserve.", action_route: "/plan", data: {}, occurred_at: "2026-08-15T00:00:00Z", read_at: null, dismissed_at: null, email_sent_at: null }] };
      if (path === "/notifications/7" && init?.method === "PATCH") return { id: 7, type: "forecast_reserve_risk", severity: "critical", title: "Cash forecast needs attention", body: "Projected cash falls below reserve.", action_route: "/plan", data: {}, occurred_at: "2026-08-15T00:00:00Z", read_at: "2026-08-15T00:01:00Z", dismissed_at: null, email_sent_at: null };
      throw new Error(`Unexpected request: ${path}`);
    });
    const user = userEvent.setup();
    render(<QueryClientProvider client={new QueryClient()}><ToastProvider><MemoryRouter><NotificationsPage /></MemoryRouter></ToastProvider></QueryClientProvider>);
    expect(await screen.findByRole("heading", { name: "Cash forecast needs attention" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Mark read" }));
    expect(vi.mocked(apiRequest)).toHaveBeenCalledWith("/notifications/7", expect.objectContaining({ method: "PATCH" }));
  });
});
