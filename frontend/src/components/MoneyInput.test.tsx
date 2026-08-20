import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MoneyInput } from "./MoneyInput";

describe("MoneyInput", () => {
  it("shows saved money with grouping separators and two decimals", () => {
    render(<label>Annual gross income<MoneyInput value="59480.0000" onValueChange={vi.fn()} locale="en-US" /></label>);
    expect(screen.getByLabelText("Annual gross income")).toHaveValue("59,480.00");
  });

  it("emits an API-safe value when the user edits formatted money", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(<label>Income<MoneyInput value="59480.0000" onValueChange={onValueChange} locale="en-US" /></label>);
    const input = screen.getByLabelText("Income");

    await user.clear(input);
    await user.type(input, "$62,500.25");

    expect(onValueChange).toHaveBeenLastCalledWith("62500.25");
  });
});
