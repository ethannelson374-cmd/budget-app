import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { AccountSummary, Category } from "../api/types";
import { TransactionEditor } from "./TransactionEditor";

const account: AccountSummary = {
  id: 1,
  institution: null,
  name: "Checking",
  official_name: null,
  display_name: "Checking",
  account_type: "depository",
  account_subtype: "checking",
  source_type: "manual",
  mask: null,
  current_balance: "1000.0000",
  available_balance: null,
  credit_limit: null,
  currency: "USD",
  last_synced_at: null,
};

const category: Category = { id: 2, key: "groceries", name: "Groceries", group: "Needs", enabled: true };

describe("TransactionEditor", () => {
  it("stores expense input with the backend's negative sign convention", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<TransactionEditor accounts={[account]} categories={[category]} busy={false} error={null} onCancel={vi.fn()} onSubmit={onSubmit} />);

    await user.selectOptions(screen.getByLabelText("Category"), "2");
    await user.type(screen.getByLabelText(/Amount/), "42.50");
    await user.type(screen.getByLabelText("Description"), "Groceries");
    await user.click(screen.getByRole("button", { name: "Add transaction" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      account_id: 1,
      category_id: 2,
      amount: "-42.50",
      kind: "expense",
      description: "Groceries",
    }));
  });
});
