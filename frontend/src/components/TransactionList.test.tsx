import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import axe from "axe-core";
import { TransactionList } from "./TransactionList";
import type { TransactionItem } from "../api/types";

const transaction: TransactionItem = {
  id: 7,
  posted_date: "2026-08-10",
  authorized_date: null,
  merchant: "Neighborhood Market",
  description: "Weekly groceries",
  original_description: null,
  payment_channel: null,
  pfc_primary: null,
  pfc_detailed: null,
  pfc_confidence: null,
  amount: "-84.2300",
  kind: "expense",
  source_type: "manual",
  pending: false,
  notes: null,
  account: { id: 3, name: "Checking", display_name: "Checking •••• 9876", mask: "•••• 9876", currency: "USD" },
  category: { id: 4, key: "groceries", name: "Groceries" },
};

describe("TransactionList", () => {
  it("renders the backend contract and masks the account", () => {
    render(<TransactionList transactions={[transaction]} />);
    expect(screen.getByText("Neighborhood Market")).toBeInTheDocument();
    expect(screen.getByText(/Checking •••• 9876/)).toBeInTheDocument();
    expect(screen.queryByText(/123456/)).not.toBeInTheDocument();
    expect(screen.getByText(/84\.23/)).toHaveClass("negative");
  });

  it("has no serious automated accessibility violations", async () => {
    const { container } = render(<TransactionList transactions={[transaction]} />);
    const result = await axe.run(container);
    expect(result.violations.filter((violation) => ["critical", "serious"].includes(violation.impact ?? ""))).toEqual([]);
  });
});
