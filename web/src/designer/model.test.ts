import { describe, expect, it } from "vitest";
import { adaptDataset, isNumeric } from "./model";
import { bindingFor, buildQuery } from "./query";

const payload = {
  tables: [
    {
      name: "Sales",
      columns: [
        { name: "Amount", data_type: "integer" },
        { name: "Status", data_type: "string" },
      ],
      measures: [{ name: "Trips" }],
    },
  ],
};

describe("dataset adapter", () => {
  it("reads snake_case tables, columns, and measures", () => {
    const tables = adaptDataset(payload);
    expect(tables).toEqual([
      {
        name: "Sales",
        fields: [
          { table: "Sales", name: "Amount", kind: "column", dataType: "integer" },
          { table: "Sales", name: "Status", kind: "column", dataType: "string" },
          { table: "Sales", name: "Trips", kind: "measure", dataType: "decimal" },
        ],
      },
    ]);
    expect(isNumeric("integer")).toBe(true);
    expect(isNumeric("string")).toBe(false);
  });
});

describe("semantic query", () => {
  it("sums a numeric column and keeps a category", () => {
    const amount = adaptDataset(payload)[0].fields[0];
    const status = adaptDataset(payload)[0].fields[1];
    const query = buildQuery({
      "x-axis": [bindingFor(status)],
      "y-axis": [bindingFor(amount)],
    });
    expect(query.select).toEqual([
      { column: { table: "Sales", column: "Status" } },
      { column: { table: "Sales", column: "Amount" }, aggregation: "sum" },
    ]);
  });

  it("adds a basic page filter", () => {
    const query = buildQuery(
      { "y-axis": [{ table: "Sales", measure: "Trips" }] },
      [
        {
          table: "Date",
          column: "Month",
          type: "basic",
          config: { operator: "eq", values: ["Jan"] },
        },
      ],
    );
    expect(query.where).toEqual([
      {
        column: { table: "Date", column: "Month" },
        operator: "eq",
        values: ["Jan"],
      },
    ]);
  });
});
