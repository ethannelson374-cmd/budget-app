import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";

vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { username: "owner", email: "owner@example.test" }, logout: vi.fn() }) }));

describe("AppShell navigation", () => {
  it("exposes only working Phase 1 destinations in desktop and mobile navigation", () => {
    render(<MemoryRouter initialEntries={["/dashboard"]}><Routes><Route element={<AppShell />}><Route path="/dashboard" element={<h1>Dashboard content</h1>} /></Route></Routes></MemoryRouter>);
    for (const name of ["Dashboard", "Accounts", "Transactions", "Settings"]) {
      expect(screen.getAllByRole("link", { name })).toHaveLength(2);
    }
    expect(screen.queryByRole("link", { name: /Budgeting|Goals|AI|Reports/ })).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Dashboard" })[0]).toHaveClass("active");
  });
});
