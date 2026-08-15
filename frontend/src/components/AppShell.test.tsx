import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import { AppShell } from "./AppShell";

vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { username: "owner", email: "owner@example.test" }, logout: vi.fn() }) }));
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn(async (path: string) => path === "/notifications/unread-count" ? { unread_count: 2 } : {}) };
});

describe("AppShell navigation", () => {
  it("exposes working destinations and the notification inbox", async () => {
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={["/dashboard"]}><Routes><Route element={<AppShell />}><Route path="/dashboard" element={<h1>Dashboard content</h1>} /></Route></Routes></MemoryRouter></QueryClientProvider>);
    for (const name of ["Dashboard", "Accounts", "Transactions", "Budget", "Plan", "Recurring", "Insights", "Advisor", "Reports", "Settings"]) {
      expect(screen.getAllByRole("link", { name })).toHaveLength(2);
    }
    expect(await screen.findAllByRole("link", { name: "2 unread notifications" })).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "Dashboard" })[0]).toHaveClass("active");
  });
});
