import { describe, expect, it } from "vitest";
import { formatMoney, maskAccount, numberFromMoney } from "./format";

describe("financial formatting", () => {
  it("keeps decimal strings accurate for presentation and rejects non-numbers", () => {
    expect(numberFromMoney("12.3400")).toBe(12.34);
    expect(numberFromMoney("not-a-number")).toBe(0);
    expect(formatMoney("12.3400", "USD")).toMatch(/12\.34/);
  });

  it("shows only the final four account digits", () => {
    expect(maskAccount("123456789")).toBe("•••• 6789");
    expect(maskAccount("•••• 4321")).toBe("•••• 4321");
    expect(maskAccount(null)).toBe("••••");
  });
});
