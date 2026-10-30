import { describe, expect, it } from "vitest";

import { tableNameFromFile } from "./GetDataDialog";

describe("tableNameFromFile", () => {
  it("turns an excel filename into a DuckDB table name", () => {
    expect(tableNameFromFile("General-Ledger.xlsx")).toBe("General_Ledger");
    expect(tableNameFromFile("Ledger.csv")).toBe("Ledger");
    expect(tableNameFromFile("2024-actuals.csv")).toBe("t_2024_actuals");
  });
});
