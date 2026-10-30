import { describe, expect, it } from "vitest";

import { CARD_FONT_MIN, fitCardFontSize } from "./cardFont";

function measure(fontSize: number, text: string): number {
  return text.length * fontSize * 0.55;
}

describe("card font", () => {
  it("uses a larger font for a short number than for a long formatted total", () => {
    const short = fitCardFontSize("42", 360, 180, measure);
    const long = fitCardFontSize("1,210,240.47", 360, 180, measure);
    expect(short).toBeGreaterThan(long);
    expect(short).toBe(72);
    expect(long).toBeGreaterThanOrEqual(CARD_FONT_MIN);
    expect(measure(long, "1,210,240.47")).toBeLessThanOrEqual(360 * 0.9);
  });
});
