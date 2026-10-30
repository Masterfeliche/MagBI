import { describe, expect, it } from "vitest";

import { EXPORT_ROW_WARNING, landscapePdfFromJpegs } from "./exportReport";

describe("export limits", () => {
  it("warns at one hundred fifty thousand rows", () => {
    expect(EXPORT_ROW_WARNING).toBe(150000);
  });

  it("builds a landscape PDF document", () => {
    const pdf = landscapePdfFromJpegs([{ bytes: new Uint8Array([0xff, 0xd8, 0xff]), width: 10, height: 10 }]);
    expect(new TextDecoder().decode(pdf.slice(0, 8))).toBe("%PDF-1.4");
    expect(new TextDecoder().decode(pdf).includes("/MediaBox [0 0 792 612]")).toBe(true);
  });
});
