import { describe, expect, it } from "vitest";

import type { VisualDefinition } from "../types/report";
import { chainTone, pillTone, sharePercent } from "./KitVisual";
import { kitQuery, memberQuery, mergeMembers } from "./query";
import { fill, formatValue, isNoData, toneOf } from "./tone";

function visual(type: string, wells: VisualDefinition["wells"], properties: Record<string, unknown> = {}): VisualDefinition {
  return { id: "v", type, x: 0, y: 0, width: 100, height: 100, wells, properties };
}

describe("tone rules", () => {
  const watchIfAny = { zero: "good" as const, otherwise: "watch" as const };
  const accuracy = { steps: [{ min: 0.98, tone: "good" as const }, { min: 0.95, tone: "watch" as const }], otherwise: "action" as const };

  it("turns a value into one status, blank first", () => {
    expect(toneOf(null, watchIfAny)).toBe("none");
    expect(toneOf(0, watchIfAny)).toBe("good");
    expect(toneOf(274, watchIfAny)).toBe("watch");
    expect(toneOf(0.993, accuracy)).toBe("good");
    expect(toneOf(0.96, accuracy)).toBe("watch");
    expect(toneOf(0.5, accuracy)).toBe("action");
    expect(toneOf(5, undefined)).toBe("info");
  });

  it("treats no-data members as grey", () => {
    expect(isNoData("Not recorded")).toBe(true);
    expect(isNoData(" not set ")).toBe(true);
    expect(isNoData("Cold chain")).toBe(false);
  });
});

describe("value formats", () => {
  it("never prints a blank as 0, NaN or (Blank)", () => {
    expect(formatValue(null)).toBe("–");
    expect(formatValue(undefined, "pct1")).toBe("–");
    expect(formatValue("", "date")).toBe("–");
  });

  it("formats whole numbers, shares, dates and signed differences", () => {
    expect(formatValue(1461)).toBe("1,461");
    expect(formatValue(1210240.4699999997)).toBe("1,210,240");
    expect(formatValue(0.99339, "pct1")).toBe("99.3%");
    expect(formatValue(0.1875, "pct0")).toBe("19%");
    expect(formatValue("2026-11-03", "date")).toBe("03 Nov 2026");
    expect(formatValue("2026-12-01T00:00:00", "monthYear")).toBe("Dec 26");
    expect(formatValue(-2, "signed")).toBe("−2");
    expect(formatValue(1, "signed")).toBe("+1");
  });

  it("fills numbered slots and marks a missing one", () => {
    expect(fill("{1} stock lines · {2} SKUs", ["1,461", "1,483", "1,454"])).toBe("1,483 stock lines · 1,454 SKUs");
    expect(fill("{3}", ["a"])).toBe("–");
  });
});

describe("kit queries", () => {
  const calendar = visual(
    "calendar",
    {
      "x-axis": [{ table: "Month", column: "MonthLabel" }],
      columns: [{ table: "Month", column: "ExpiryMonth" }, { table: "Month", column: "InNext90Days" }],
      "y-axis": [{ table: "Batch", measure: "Batches" }],
    },
    { allMembers: true },
  );

  it("selects the wells in role order with the visual's filters", () => {
    const query = kitQuery(calendar, [{ table: "Warehouse", column: "Warehouse", type: "basic", config: { operator: "in", values: ["CW2"] } }]);
    expect(query?.select.map((item) => item.column?.column ?? item.measure?.measure)).toEqual(["MonthLabel", "ExpiryMonth", "InNext90Days", "Batches"]);
    expect(query?.where).toEqual([{ column: { table: "Warehouse", column: "Warehouse" }, operator: "in", values: ["CW2"] }]);
  });

  it("asks for every member without filters and keeps months that have no rows", () => {
    expect(memberQuery(calendar)?.select).toHaveLength(3);
    expect(memberQuery({ ...calendar, properties: {} })).toBeNull();
    const rows = [["Dec 26", "2026-12-01", 1, 118]];
    const members = [["Nov 26", "2026-11-01", 1], ["Dec 26", "2026-12-01", 1], ["Apr 27", "2027-04-01", 0]];
    expect(mergeMembers(calendar, rows, members)).toEqual([
      ["Nov 26", "2026-11-01", 1, null],
      ["Dec 26", "2026-12-01", 1, 118],
      ["Apr 27", "2027-04-01", 0, null],
    ]);
  });

  it("passes the grid's sort and row limit to the server", () => {
    const grid = visual("grid", { columns: [{ table: "Batch", column: "Item" }, { table: "Batch", column: "DaysLeft" }] }, {
      orderBy: [{ select: 1, direction: "asc" }],
      limit: 25,
    });
    const query = kitQuery(grid, []);
    expect(query?.orderBy).toEqual([{ select: 1, direction: "asc" }]);
    expect(query?.limit).toBe(25);
  });
});

describe("chain and pill status", () => {
  it("follows the WMS flow rule: empty, flagged, too old, then the base tone", () => {
    expect(chainTone(0, 19, 0, 2, "info", "watch")).toBe("none");
    expect(chainTone(1456, null, 1, null, "good", "action")).toBe("action");
    expect(chainTone(4, 19, 0, 2, "info", "watch")).toBe("watch");
    expect(chainTone(18, null, 0, null, "good", "watch")).toBe("good");
  });

  it("takes a pill's tone from a rule, a value map or another column", () => {
    const days = { rule: { steps: [{ max: 30, tone: "action" as const }, { max: 90, tone: "watch" as const }] } };
    expect(pillTone(days, 9, [])).toBe("action");
    expect(pillTone(days, 45, [])).toBe("watch");
    expect(pillTone({ map: { Open: "watch", Closed: "good" } }, "Closed", [])).toBe("good");
    expect(pillTone({ toneFrom: 2 }, "Short", ["x", 1, "watch"])).toBe("watch");
  });
});

describe("shares", () => {
  it("never rounds a part that exists to 0% or 100%", () => {
    expect(sharePercent(99.5)).toBe("99.5%");
    expect(sharePercent(99.95)).toBe("99.9%");
    expect(sharePercent(100)).toBe("100%");
    expect(sharePercent(0.3)).toBe("<1%");
    expect(sharePercent(41.48)).toBe("41%");
  });
});
