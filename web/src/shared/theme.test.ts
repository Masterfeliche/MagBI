/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";

import kitCss from "../kit/kit.css?raw";
import { buildEChartsTheme, cssVars, DEFAULT_THEME, resolveTheme, themeForReport, tokenColour, withAlpha } from "./theme";

describe("report themes", () => {
  it("defaults to Enterprise Light with the ERP Native colours", () => {
    expect(DEFAULT_THEME.id).toBe("enterprise-light");
    expect(DEFAULT_THEME.data.categorical[0]).toBe("#3F6FB0");
    expect(DEFAULT_THEME.status.watch.glyph).toBe("◆");
  });

  it("merges layers in order, later ones winning", () => {
    const theme = resolveTheme(DEFAULT_THEME, [
      { surface: { page: "#111111" }, text: { ink: "#222222" } },
      undefined,
      { surface: { page: "#333333" } },
    ]);
    expect(theme.surface.page).toBe("#333333");
    expect(theme.text.ink).toBe("#222222");
    expect(theme.surface.panel).toBe(DEFAULT_THEME.surface.panel);
    expect(DEFAULT_THEME.surface.page).toBe("#EEF2F7");
  });

  it("lets a locked layer keep later layers to chart colours only", () => {
    const theme = resolveTheme(DEFAULT_THEME, [
      { locked: true, text: { ink: "#101010" } },
      { text: { ink: "#999999" }, data: { categorical: ["#123456"] } },
    ]);
    expect(theme.text.ink).toBe("#101010");
    expect(theme.data.categorical).toEqual(["#123456"]);
  });

  it("reads the theme fields stored on a report", () => {
    const theme = themeForReport({ colors: ["#3F6FB0", "#5F8BC9"], background: "#EEF2F7" });
    expect(theme.data.categorical).toEqual(["#3F6FB0", "#5F8BC9"]);
    expect(theme.surface.page).toBe("#EEF2F7");
    expect(themeForReport(undefined)).toEqual(DEFAULT_THEME);
  });

  it("resolves token names and leaves literal colours alone", () => {
    expect(tokenColour(DEFAULT_THEME, "frame", "line")).toBe("#F8FAFC");
    expect(tokenColour(DEFAULT_THEME, undefined, "line")).toBe("#D3DCE6");
    expect(tokenColour(DEFAULT_THEME, "ink", "line")).toBe("#22324A");
    expect(tokenColour(DEFAULT_THEME, "#ABCDEF", "line")).toBe("#ABCDEF");
  });

  it("tints a colour and builds the shared chart options", () => {
    expect(withAlpha("#3F6FB0", 0.25)).toBe("rgba(63,111,176,0.25)");
    const charts = buildEChartsTheme(DEFAULT_THEME);
    expect(charts.base.color).toEqual(DEFAULT_THEME.data.categorical);
    expect(charts.splitLine.lineStyle.color).toBe("#E2E8EF");
  });

  it("defines every variable the kit stylesheet uses", () => {
    const css = kitCss;
    const used = new Set([...css.matchAll(/var\((--mb-[\w-]+)\)/g)].map((match) => match[1]));
    const defined = Object.keys(cssVars(DEFAULT_THEME));
    expect([...used].filter((name) => !defined.includes(name))).toEqual([]);
    expect(css).not.toMatch(/#[0-9a-f]{3,6}\b|rgba?\(/i);
  });
});
