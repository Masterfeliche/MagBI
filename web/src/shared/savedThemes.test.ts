import { describe, expect, it } from "vitest";

import { builtInTheme, DEFAULT_THEME, themeForReport, type SavedTheme, type SavedThemes } from "./theme";

function saved(id: string, scope: SavedTheme["scope"], definition: SavedTheme["definition"], extra: Partial<SavedTheme> = {}): SavedTheme {
  return { id, scope, name: id, definition, isDefault: false, locked: false, version: 1, ...extra };
}

const brand = saved("brand", "organisation", { extends: "finance", text: { accent: "#123456" } }, { isDefault: true });
const team = saved("team", "workspace", { extends: "health" }, { isDefault: true });

describe("saved themes", () => {
  it("gives a report that has not picked a theme the workspace default, then the organisation's", () => {
    expect(themeForReport(undefined, { organisation: [brand], workspace: [team] }).id).toBe("saved:team");
    const org = themeForReport(undefined, { organisation: [brand], workspace: [] });
    expect(org.id).toBe("saved:brand");
    expect(org.text.accent).toBe("#123456");
    expect(org.surface.page).toBe(builtInTheme("finance").surface.page);
    expect(themeForReport(undefined, { organisation: [], workspace: [] })).toEqual(DEFAULT_THEME);
  });

  it("keeps a report's own pick and its own changes", () => {
    const all: SavedThemes = { organisation: [brand], workspace: [team] };
    expect(themeForReport({ id: "retail" }, all).id).toBe("retail");
    expect(themeForReport({ id: "saved:brand", overrides: { surface: { page: "#FAFAFA" } } }, all).surface.page).toBe("#FAFAFA");
  });

  it("holds every report to a locked organisation theme, chart colours aside", () => {
    const locked: SavedThemes = { organisation: [{ ...brand, locked: true }], workspace: [team] };
    const theme = themeForReport({ id: "retail", overrides: { surface: { page: "#FAFAFA" }, data: { categorical: ["#111111"] } } }, locked);
    expect(theme.id).toBe("saved:brand");
    expect(theme.surface.page).toBe(builtInTheme("finance").surface.page);
    expect(theme.data.categorical).toEqual(["#111111"]);
  });
});
