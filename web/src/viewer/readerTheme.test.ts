import { describe, expect, it } from "vitest";

import { embedUrlFor } from "../embed/sdk";
import { builtInTheme, DEFAULT_THEME, forReader, themeForReport, type SavedThemes } from "../shared/theme";
import { hostThemeFrom } from "./readerTheme";

const lockedBrand: SavedThemes = {
  organisation: [{ id: "brand", scope: "organisation", name: "Brand", definition: { extends: "finance" }, isDefault: true, locked: true, version: 1 }],
  workspace: [],
};

describe("reader themes", () => {
  it("gives High Contrast even over a locked organisation theme", () => {
    const brand = themeForReport({ id: "retail" }, lockedBrand);
    expect(brand.id).toBe("saved:brand");
    expect(forReader(brand, { contrast: true, larger: false })).toEqual(builtInTheme("high-contrast"));
  });

  it("makes text larger on top of the brand without changing its colours", () => {
    const brand = themeForReport(undefined, lockedBrand);
    const larger = forReader(brand, { contrast: false, larger: true });
    expect(larger.type.scale).toBe(1.15);
    expect(larger.shape.touch).toBe(44);
    expect(larger.surface).toEqual(brand.surface);
    expect(forReader(builtInTheme("presentation"), { contrast: false, larger: true }).type.scale).toBe(1.2);
    expect(forReader(DEFAULT_THEME, { contrast: false, larger: false })).toBe(DEFAULT_THEME);
  });
});

describe("embedded reports", () => {
  it("takes a host app's theme pick and ignores unknown ids", () => {
    expect(hostThemeFrom({ id: "health" })).toEqual({ id: "health" });
    expect(hostThemeFrom({ id: "saved:abc" })).toEqual({ id: "saved:abc" });
    expect(hostThemeFrom({ id: "neon" })).toBeNull();
    expect(hostThemeFrom({ overrides: { data: { categorical: ["#0B5394"] } } })).toEqual({ overrides: { data: { categorical: ["#0B5394"] } } });
    expect(themeForReport(hostThemeFrom({ id: "health" }) ?? undefined, lockedBrand).id).toBe("saved:brand");
  });

  it("puts the host's theme id and High Contrast in the embed URL", () => {
    expect(embedUrlFor("r1", "tok", undefined, "https://bi.example", { id: "health", contrast: true })).toBe(
      "https://bi.example/embed/r1?token=tok&themeId=health&contrast=1",
    );
  });
});
