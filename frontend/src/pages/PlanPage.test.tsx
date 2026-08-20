import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import { PlanPage } from "./PlanPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});
vi.mock("./BudgetPage", () => ({ BudgetPage: () => <div>Budget workspace</div> }));

describe("PlanPage consolidation", () => {
  it("opens the existing Budget experience inside Plan", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={["/plan?tab=budget"]}><PlanPage /></MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("heading", { name: "Plan" })).toBeInTheDocument();
    expect(screen.getByText("Budget workspace")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Budget" })).toHaveClass("active");
  });
});
