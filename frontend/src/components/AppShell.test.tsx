import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import { AppShell } from "./AppShell";

vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { username: "owner", email: "owner@example.test" }, logout: vi.fn() }) }));
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn(async (path: string) => path === "/notifications/unread-count" ? { unread_count: 2 } : {}) };
});

describe("AppShell navigation", () => {
  beforeEach(() => localStorage.clear());

  function renderShell() {
    return render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={["/dashboard"]}><Routes><Route element={<AppShell />}><Route path="/dashboard" element={<h1>Dashboard content</h1>} /></Route></Routes></MemoryRouter></QueryClientProvider>);
  }

  it("exposes working destinations and the notification inbox", async () => {
    renderShell();
    for (const name of ["Dashboard", "Accounts", "Transactions", "Budget", "Plan", "Recurring", "Insights", "Advisor", "Reports", "Settings"]) {
      expect(screen.getAllByRole("link", { name })).toHaveLength(2);
    }
    expect(await screen.findAllByRole("link", { name: "2 unread notifications" })).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "Dashboard" })[0]).toHaveClass("active");
  });

  it("starts as an icon rail and exposes an accessible navigation resizer", () => {
    const { container } = renderShell();
    const shell = container.querySelector(".app-shell");
    const resizer = screen.getByRole("separator", { name: "Resize navigation" });
    expect(shell).toHaveAttribute("data-nav-mode", "compact");
    expect(resizer).toHaveAttribute("aria-valuetext", "Icons only");
    fireEvent.keyDown(resizer, { key: "End" });
    expect(shell).toHaveAttribute("data-nav-mode", "full");
    expect(resizer).toHaveAttribute("aria-valuetext", "Full navigation");
    expect(localStorage.getItem("budget-liquid-nav-width")).toBe("252");
  });
});
