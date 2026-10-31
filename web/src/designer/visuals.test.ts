import { describe, expect, it } from "vitest";

import type { DSR } from "../types/query";
import { visualSpec, VISUALS } from "./catalog";
import { matchRegions, regionKey } from "./maps";
import { buildMatrix, expandablePaths, matrixQueries, TOTAL, visibleRows } from "./matrix";
import { buildQuery } from "./query";
import { percentOfCategory, renderModel } from "./render";

const dsr = (columns: [string, boolean][], rows: unknown[][]): DSR => ({
  columns: columns.map(([name, isMeasure]) => ({ name, dataType: isMeasure ? "integer" : "string", isMeasure })),
  rows,
  rowCount: rows.length,
});

describe("stacked, 100% stacked, area and combo charts", () => {
  const sales = dsr([["Region", false], ["Gloves", true], ["Masks", true]], [["North", 6, 2], ["South", 1, 3]]);

  it("carries the stack, area and line settings into the model", () => {
    const stacked = renderModel("stackedColumn", sales);
    expect(stacked.kind === "cartesian" && stacked.stack).toBe("stacked");
    const share = renderModel("bar100", sales);
    expect(share.kind === "cartesian" && share.stack).toBe("percent");
    const area = renderModel("stackedArea", sales);
    expect(area.kind === "cartesian" && area.area && area.stack).toBe("stacked");
    const combo = renderModel("combo", sales, 0, { lineCount: 1 });
    expect(combo.kind === "cartesian" && combo.lineCount).toBe(1);
  });

  it("turns each category into shares of 100", () => {
    expect(percentOfCategory([{ name: "Gloves", values: [6, 1] }, { name: "Masks", values: [2, 3] }])).toEqual([
      { name: "Gloves", values: [75, 25] },
      { name: "Masks", values: [25, 75] },
    ]);
  });

  it("asks for the line values after the column values", () => {
    const query = buildQuery({
      "x-axis": [{ table: "Sales", column: "Region" }],
      "y-axis": [{ table: "Sales", measure: "Qty" }],
      line: [{ table: "Sales", measure: "Target" }],
    });
    expect(query.select.map((item) => ("measure" in item ? item.measure.measure : item.column.column))).toEqual(["Region", "Qty", "Target"]);
  });
});

describe("matrix", () => {
  const wells = {
    rows: [{ table: "Region", column: "Region" }, { table: "Sales", column: "Product" }],
    columns: [{ table: "Date", column: "Year" }],
    values: [{ table: "Sales", measure: "Avg price" }],
  };

  it("asks the engine for every subtotal level, with and without the column field", () => {
    const queries = matrixQueries(wells, []);
    expect(queries.map((item) => `${item.level.depth}${item.level.byColumn ? "c" : ""}`)).toEqual(["0", "0c", "1", "1c", "2", "2c"]);
    expect(queries[5]?.query.select).toHaveLength(4);
    expect(matrixQueries({ rows: wells.rows }, [])).toEqual([]);
  });

  it("builds rows, subtotals and totals from the engine's own figures", () => {
    // An average is not additive: the North subtotal (5) is not 4 + 8.
    const answers = [
      { level: { depth: 0, byColumn: false }, dsr: dsr([["Avg price", true]], [[6]]) },
      { level: { depth: 0, byColumn: true }, dsr: dsr([["Year", false], ["Avg price", true]], [[2025, 5], [2026, 7]]) },
      { level: { depth: 1, byColumn: false }, dsr: dsr([["Region", false], ["Avg price", true]], [["South", 9], ["North", 5]]) },
      { level: { depth: 1, byColumn: true }, dsr: dsr([["Region", false], ["Year", false], ["Avg price", true]], [["North", 2025, 4], ["South", 2026, 9]]) },
      { level: { depth: 2, byColumn: false }, dsr: dsr([["Region", false], ["Product", false], ["Avg price", true]], [["North", "Masks", 8], ["North", "Gloves", 4], ["South", null, 9]]) },
      { level: { depth: 2, byColumn: true }, dsr: dsr([["Region", false], ["Product", false], ["Year", false], ["Avg price", true]], [["North", "Gloves", 2025, 4]]) },
    ];
    const matrix = buildMatrix(answers, 2, true);
    expect(matrix.columns).toEqual(["2025", "2026"]);
    expect(matrix.rows.map((row) => row.label)).toEqual(["North", "South"]);
    const north = matrix.rows[0]!;
    expect(north.cells.get(TOTAL)).toEqual([5]);
    expect(north.cells.get("2025")).toEqual([4]);
    expect(north.children.map((child) => child.label)).toEqual(["Gloves", "Masks"]);
    expect(matrix.rows[1]!.children[0]!.label).toBe("Not set");
    expect(matrix.total.get(TOTAL)).toEqual([6]);
    expect(matrix.total.get("2026")).toEqual([7]);

    expect(visibleRows(matrix.rows, new Set()).map((row) => row.label)).toEqual(["North", "South"]);
    const all = new Set(expandablePaths(matrix.rows));
    expect(visibleRows(matrix.rows, all).map((row) => row.label)).toEqual(["North", "Gloves", "Masks", "South", "Not set"]);
  });
});

describe("maps", () => {
  it("places points by latitude and longitude and skips rows without them", () => {
    const sites = dsr([["Warehouse", false], ["Lat", false], ["Lon", false], ["Stock", true]], [
      ["Dodoma", -6.17, 35.74, 120],
      ["Mwanza", -2.52, 32.9, 80],
      ["Nowhere", null, "x", 5],
    ]);
    const model = renderModel("map", sites);
    expect(model.kind).toBe("map");
    if (model.kind === "map") expect(model.points.map((point) => point.name)).toEqual(["Dodoma", "Mwanza"]);
  });

  it("matches region names however they are spelled", () => {
    expect(regionKey("Dar-es-Salaam Region")).toBe(regionKey("Dar es salaam"));
    const regions = { type: "FeatureCollection", features: [{ properties: { shapeName: "Dar es Salaam" } }, { properties: { name: "Mwanza" } }] };
    const { matched, unmatched } = matchRegions(regions, [
      { name: "DAR-ES-SALAAM", value: 3 },
      { name: "Mwanza Region", value: 2 },
      { name: "Atlantis", value: 1 },
    ]);
    expect(matched).toEqual([{ name: "Dar es Salaam", value: 3 }, { name: "Mwanza", value: 2 }]);
    expect(unmatched).toEqual(["Atlantis"]);
  });

  it("has a filled map and a point map in the gallery", () => {
    expect(visualSpec("filledMap").renders).toBe("filledMap");
    expect(VISUALS.find((spec) => spec.type === "map")?.wells.map((well) => well.name)).toEqual(["x-axis", "latitude", "longitude", "y-axis"]);
  });
});

describe("gallery", () => {
  it("lists only visuals that draw something", async () => {
    const { isKitType } = await import("../kit/query");
    const silent = VISUALS.filter((spec) => spec.renders === "none" && !isKitType(spec.type)).map((spec) => spec.type);
    expect(silent).toEqual([]);
  });
});

describe("chart titles and legends", () => {
  it("puts a top legend on its own line under the title and makes room for it", async () => {
    const { legendFrom, plotTop } = await import("./formatChart");
    expect(legendFrom({ title: "Sales" }).top).toBe(26);
    expect(legendFrom({}).top).toBe("top");
    expect(plotTop({ title: "Sales" }, 3)).toBe(62);
    expect(plotTop({ title: "Sales" }, 1)).toBe(38);
    expect(plotTop({ legendPos: "Bottom" }, 3)).toBe(16);
  });
});
