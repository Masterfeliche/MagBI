import { describe, expect, it } from "vitest";

import type { VisualDefinition } from "../types/report";
import { buildQuery } from "./query";
import {
  categoryOpacity,
  filtersForVisual,
  groupingOf,
  pageFilter,
  patchFormat,
  toggleCrossFilter,
} from "./filters";

const visual: VisualDefinition = {
  id: "bar-1",
  type: "bar",
  x: 0,
  y: 0,
  width: 360,
  height: 240,
  wells: { "x-axis": [{ table: "Trips", column: "Month" }] },
};

describe("filters and format", () => {
  it("toggles a category filter, keeps page filters on every query, and patches title and color", () => {
    const page = [pageFilter("Trips", "Status", "eq", "Open")];
    const on = toggleCrossFilter(null, visual.id, "Trips", "Month", "Jan");
    expect(on).toEqual({ sourceId: "bar-1", table: "Trips", column: "Month", value: "Jan" });
    expect(toggleCrossFilter(on, visual.id, "Trips", "Month", "Jan")).toBeNull();

    const source = filtersForVisual(page, on, visual.id);
    const other = filtersForVisual(page, on, "card-1");
    expect(buildQuery(visual.wells, source).where).toEqual([
      { column: { table: "Trips", column: "Status" }, operator: "eq", values: ["Open"] },
    ]);
    expect(buildQuery({ "y-axis": [{ table: "Trips", measure: "Trips" }] }, other).where).toEqual([
      { column: { table: "Trips", column: "Status" }, operator: "eq", values: ["Open"] },
      { column: { table: "Trips", column: "Month" }, operator: "eq", values: ["Jan"] },
    ]);
    expect(groupingOf(visual)).toEqual({ table: "Trips", column: "Month" });
    expect(categoryOpacity("Jan", "Jan")).toBe(1);
    expect(categoryOpacity("Feb", "Jan")).toBe(0.3);
    expect(patchFormat(visual, "Trips", "#118DFF").properties).toEqual({
      title: "Trips",
      color: "#118DFF",
    });
  });
});
