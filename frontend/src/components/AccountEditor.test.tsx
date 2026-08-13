import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AccountEditor } from "./AccountEditor";

describe("AccountEditor", () => {
  it("submits a manual account payload and normalizes currency", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<AccountEditor defaultCurrency="USD" busy={false} error={null} onCancel={vi.fn()} onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Name"), "Main checking");
    await user.clear(screen.getByLabelText(/Current balance/));
    await user.type(screen.getByLabelText(/Current balance/), "1234.56");
    await user.clear(screen.getByLabelText("Currency"));
    await user.type(screen.getByLabelText("Currency"), "usd");
    await user.click(screen.getByRole("button", { name: "Add account" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      name: "Main checking",
      current_balance: "1234.56",
      currency: "USD",
      account_type: "depository",
    }));
  });
});
