import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import { TransactionsPage } from "./TransactionsPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});

describe("TransactionsPage filters", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset().mockImplementation(async (path) => {
      if (path === "/accounts") return { accounts: [] };
      if (path === "/categories/selection") return { categories: [] };
      return { items: [], page: 1, page_size: 25, total: 0, pages: 0 };
    });
  });

  it("uses the backend's exact filter and sort parameter names", async () => {
    const user = userEvent.setup();
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><TransactionsPage /></MemoryRouter></QueryClientProvider>);
    const search = await screen.findByLabelText("Search");
    await user.type(search, "Coffee 100%_shop");
    await user.selectOptions(screen.getByLabelText("Sort by"), "merchant");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(vi.mocked(apiRequest).mock.calls.some(([path]) => typeof path === "string" && path.startsWith("/transactions?") && path.includes("search=Coffee+100%25_shop") && path.includes("sort=merchant") && path.includes("page_size=25"))).toBe(true));
  });
});
