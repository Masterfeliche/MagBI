import { describe, expect, it } from "vitest";

import type { DSR } from "../types/query";
import { renderModel } from "./render";

const trips: DSR = {
  columns: [
    { name: "Month", dataType: "string", isMeasure: false },
    { name: "Trips", dataType: "integer", isMeasure: true },
  ],
  rows: [
    ["Jan", 10],
    ["Feb", 12],
  ],
  rowCount: 2,
};

describe("visual render models", () => {
  it("draws bar, pie, card, and table, and leaves the other types as notes", () => {
    const bar = renderModel("bar", trips);
    expect(bar.kind).toBe("cartesian");
    if (bar.kind === "cartesian") {
      expect(bar.orientation).toBe("bar");
      expect(bar.categories).toEqual(["Jan", "Feb"]);
      expect(bar.series[0]?.values).toEqual([10, 12]);
    }

    const pie = renderModel("pie", trips);
    expect(pie.kind).toBe("pie");
    if (pie.kind === "pie") expect(pie.slices[0]).toEqual({ name: "Jan", value: 10 });

    const card = renderModel("card", trips);
    expect(card).toEqual({ kind: "card", value: "10" });

    const table = renderModel("table", trips);
    expect(table.kind).toBe("table");
    if (table.kind === "table") expect(table.columns).toEqual(["Month", "Trips"]);

    const map = renderModel("map", trips);
    expect(map.kind).toBe("note");
    if (map.kind === "note") expect(map.message).toContain("latitude");

    expect(renderModel("line", null)).toMatchObject({ kind: "note" });
  });

  it("keeps trailing tooltip columns off the series", () => {
    const withTooltip: DSR = {
      columns: [
        { name: "Month", dataType: "string", isMeasure: false },
        { name: "Trips", dataType: "integer", isMeasure: true },
        { name: "Dept", dataType: "string", isMeasure: false },
      ],
      rows: [
        ["Jan", 10, "HR"],
        ["Feb", 12, "IT"],
      ],
      rowCount: 2,
    };
    const bar = renderModel("bar", withTooltip, 1);
    expect(bar.kind).toBe("cartesian");
    if (bar.kind === "cartesian") {
      expect(bar.series).toHaveLength(1);
      expect(bar.tooltips?.[0]).toEqual({ name: "Dept", values: ["HR", "IT"] });
    }
  });

  it("renders scatter, funnel, gauge, treemap, and waterfall from a DSR", () => {
    expect(renderModel("scatter", trips).kind).toBe("scatter");
    expect(renderModel("funnel", trips).kind).toBe("funnel");
    expect(renderModel("gauge", trips).kind).toBe("gauge");
    expect(renderModel("treemap", trips).kind).toBe("treemap");
    expect(renderModel("waterfall", trips).kind).toBe("waterfall");
  });
});
