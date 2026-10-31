import { describe, expect, it } from "vitest";

import { insertText, searchFunctions, type DaxFunction } from "./daxFunctions";

const all: DaxFunction[] = [
  { name: "SUMX", signature: "SUMX(<table>, <row expression>)", description: "Adds up an expression worked out row by row." },
  { name: "SUM", signature: "SUM(<column>)", description: "Adds up a numeric column." },
  { name: "RANKX", signature: "RANKX(...)", description: "The rank of each row of the visual." },
];

describe("DAX function list", () => {
  it("finds names first, then descriptions", () => {
    expect(searchFunctions(all, "sum").map((item) => item.name)).toEqual(["SUMX", "SUM"]);
    expect(searchFunctions(all, "rank").map((item) => item.name)).toEqual(["RANKX"]);
    expect(searchFunctions(all, "row").map((item) => item.name)).toEqual(["SUMX", "RANKX"]);
    expect(searchFunctions(all, "  ")).toHaveLength(3);
  });

  it("inserts the name and an open bracket", () => {
    expect(insertText(all[0])).toBe("SUMX(");
  });
});
