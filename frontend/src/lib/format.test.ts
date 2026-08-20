import { describe, expect, it } from "vitest";
import { formatMoney, formatMoneyInput, maskAccount, normalizeMoneyInput, numberFromMoney } from "./format";

describe("financial formatting", () => {
  it("keeps decimal strings accurate for presentation and rejects non-numbers", () => {
    expect(numberFromMoney("12.3400")).toBe(12.34);
    expect(numberFromMoney("not-a-number")).toBe(0);
    expect(formatMoney("12.3400", "USD")).toMatch(/12\.34/);
  });

  it("formats editable money values without leaking database precision", () => {
    expect(formatMoneyInput("59480.0000", "en-US")).toBe("59,480.00");
    expect(formatMoneyInput("1,234.5", "en-US")).toBe("1,234.50");
    expect(normalizeMoneyInput("$59,480.00")).toBe("59480.00");
  });

  it("shows only the final four account digits", () => {
    expect(maskAccount("123456789")).toBe("•••• 6789");
    expect(maskAccount("•••• 4321")).toBe("•••• 4321");
    expect(maskAccount(null)).toBe("••••");
  });
});
