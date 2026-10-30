import { describe, expect, it } from "vitest";

import { cardSignColor, colorScale, dataBarWidth, statusColor } from "./condFormat";

describe("conditional format", () => {
  it("colors status, card sign, a scale, and a data bar", () => {
    expect(statusColor("Approved")).toBe("#10B981");
    expect(statusColor("Rejected")).toBe("#EF4444");
    expect(cardSignColor("-12")).toBe("#EF4444");
    expect(cardSignColor("12")).toBe("#10B981");
    expect(colorScale([0, 10], 10)).toMatch(/^rgb\(/);
    expect(dataBarWidth([10, 20], 10)).toBe("50%");
  });
});
