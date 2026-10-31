import { describe, expect, it } from "vitest";

import { BUILT_IN_THEMES, builtInTheme, DEFAULT_THEME, resolveTheme } from "./theme";
import { contrast, themeProblems } from "./themeCheck";
import { exportThemeFile, importThemeFile } from "./themeFile";

describe("built-in themes", () => {
  it("ships nine themes, default first, each passing every check", () => {
    expect(BUILT_IN_THEMES.map((theme) => theme.id)).toEqual([
      "enterprise-light",
      "classic",
      "health",
      "finance",
      "government",
      "retail",
      "mobile",
      "presentation",
      "high-contrast",
    ]);
    for (const theme of BUILT_IN_THEMES) expect(themeProblems(theme), theme.id).toEqual([]);
  });

  it("fills a theme that extends another from its parent", () => {
    const mobile = builtInTheme("mobile");
    expect(mobile.type.scale).toBe(1.15);
    expect(mobile.surface).toEqual(DEFAULT_THEME.surface);
    expect(builtInTheme("presentation").chart.gridlines).toBe(false);
    expect(builtInTheme("high-contrast").pattern).toBe(true);
  });
});

describe("theme checks", () => {
  it("matches WCAG contrast", () => {
    expect(contrast("#000000", "#FFFFFF")).toBeCloseTo(21, 1);
    expect(contrast("#777777", "#FFFFFF")).toBeCloseTo(4.48, 1);
  });

  it("names unreadable text and clashing colours", () => {
    const bad = resolveTheme(DEFAULT_THEME, [
      { text: { muted: "#C0C0C0" }, data: { style: "categorical", categorical: ["#3F6FB0", "#4070B0", "#4E9E77"] } },
    ]);
    const found = themeProblems(bad).join(" | ");
    expect(found).toMatch(/Muted text on page is hard to read/);
    expect(found).toMatch(/too alike/);
    expect(found).toMatch(/looks like the On track status/);
  });
});

describe("theme files", () => {
  it("reads a Power BI theme", () => {
    const imported = importThemeFile(
      JSON.stringify({
        name: "Contoso",
        dataColors: ["#118dff", "#12239E", "not a colour"],
        background: "#FFFFFF",
        foreground: "#252423",
        tableAccent: "#118DFF",
        good: "#1AAB40",
        neutral: "#D9B300",
        bad: "#D64554",
        textClasses: { label: { fontFace: "Arial" } },
        visualStyles: { page: { "*": { background: [{ color: { solid: { color: "#F3F2F1" } } }] } } },
      }),
    );
    expect(imported.name).toBe("Contoso");
    const theme = resolveTheme(DEFAULT_THEME, [imported.layer]);
    expect(theme.data.categorical).toEqual(["#118DFF", "#12239E"]);
    expect(theme.data.style).toBe("categorical");
    expect(theme.surface.page).toBe("#F3F2F1");
    expect(theme.text.ink).toBe("#252423");
    expect(theme.status.watch.color).toBe("#D9B300");
    expect(theme.status.watch.glyph).toBe("◆");
    expect(theme.type.family).toBe("Arial");
  });

  it("round-trips every built-in theme through export and import", () => {
    for (const theme of BUILT_IN_THEMES) {
      const file = JSON.parse(exportThemeFile(theme)) as { dataColors: string[]; good: string };
      expect(file.dataColors).toEqual(theme.data.categorical);
      expect(file.good).toBe(theme.status.good.color);
      const back = importThemeFile(exportThemeFile(theme));
      expect(back.base).toBe(theme.id);
      expect(resolveTheme(builtInTheme(back.base), [back.layer])).toEqual(theme);
    }
  });

  it("says plainly why a file is refused", () => {
    expect(() => importThemeFile("{")).toThrow("not valid JSON");
    expect(() => importThemeFile(JSON.stringify({ name: "Empty" }))).toThrow("no theme colours");
  });
});
