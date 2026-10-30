import { describe, expect, it } from "vitest";

import { isRefreshDone, mergeImportTables, SCHEDULE_PRESETS } from "./refreshPlan";

describe("refresh plan", () => {
  it("adds a new source table and skips a name that already exists", () => {
    const result = mergeImportTables(
      { connection_id: "c1", tables: [{ name: "Sales" }] },
      [
        { schema: "dbo", name: "Sales" },
        { schema: "dbo", name: "Orders" },
      ],
    );
    expect(result.added).toEqual(["Orders"]);
    const tables = result.definition.tables as { name: string; source: { schema: string; table: string } }[];
    expect(tables).toHaveLength(2);
    expect(tables[1].source).toEqual({ type: "table", schema: "dbo", table: "Orders" });
  });

  it("uses five-field cron presets and knows when a refresh has finished", () => {
    expect(SCHEDULE_PRESETS.every((preset) => preset.cron.split(" ").length === 5)).toBe(true);
    expect(isRefreshDone("running")).toBe(false);
    expect(isRefreshDone("succeeded")).toBe(true);
    expect(isRefreshDone("failed")).toBe(true);
  });
});
