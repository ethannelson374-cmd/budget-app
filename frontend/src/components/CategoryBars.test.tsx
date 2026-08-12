import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { formatMoney } from "../lib/format";
import { CategoryBars } from "./CategoryBars";

describe("CategoryBars", () => {
  it("preserves negative net spending when refunds exceed expenses", () => {
    render(
      <CategoryBars
        currency="USD"
        categories={[
          { key: "groceries", name: "Groceries", amount: "100.0000" },
          { key: "restaurants", name: "Restaurants", amount: "-25.0000" },
        ]}
      />,
    );

    const displayedRefund = screen.getByText(formatMoney("-25.0000", "USD"));
    expect(displayedRefund).toHaveClass("positive");
    expect(screen.getByRole("meter", { name: `Restaurants: ${formatMoney("-25.0000", "USD")}` })).toHaveAttribute("aria-valuenow", "25");
  });
});
