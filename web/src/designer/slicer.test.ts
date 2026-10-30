import { describe, expect, it } from "vitest";

import { slicerFilters } from "./slicer";

describe("slicerFilters", () => {
  it("writes an in filter for list selections and range bounds", () => {
    expect(slicerFilters("Ledger", "Dept", "list", ["HR", "IT"])).toEqual([
      {
        table: "Ledger",
        column: "Dept",
        type: "basic",
        config: { operator: "in", values: ["HR", "IT"] },
      },
    ]);
    expect(slicerFilters("Ledger", "Amount", "range", [], { min: "10", max: "50" })).toEqual([
      { table: "Ledger", column: "Amount", type: "basic", config: { operator: "gte", values: ["10"] } },
      { table: "Ledger", column: "Amount", type: "basic", config: { operator: "lte", values: ["50"] } },
    ]);
  });
});
