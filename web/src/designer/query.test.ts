import { describe, expect, it } from "vitest";

import { buildQuery } from "./query";

describe("buildQuery", () => {
  it("uses the hierarchy level as the category and appends tooltip fields", () => {
    const query = buildQuery(
      {
        "x-axis": [{ table: "Ledger", column: "Year" }],
        hierarchy: [
          { table: "Ledger", column: "Year" },
          { table: "Ledger", column: "Month" },
        ],
        "y-axis": [{ table: "Ledger", column: "Credit", aggregation: "sum" }],
        tooltips: [{ table: "Ledger", column: "Department" }],
      },
      [],
      { drillLevel: 1 },
    );
    expect(query.select[0]).toEqual({ column: { table: "Ledger", column: "Month" } });
    expect(query.select.at(-1)).toEqual({ column: { table: "Ledger", column: "Department" } });
  });
});
