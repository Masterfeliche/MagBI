import { describe, expect, it } from "vitest";

import { colorsFromThemeJson } from "./themes";

describe("Power BI theme JSON", () => {
  it("reads dataColors for every visual", () => {
    expect(colorsFromThemeJson(JSON.stringify({ dataColors: ["#111", "#222"] }))).toEqual(["#111", "#222"]);
  });
});
