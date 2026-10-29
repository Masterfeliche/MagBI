import { describe, expect, it } from "vitest";

import { visualSpec } from "./catalog";
import type { DesignerField } from "./model";
import { dropField } from "./wells";

const month: DesignerField = { table: "Trips", name: "Month", kind: "column", dataType: "string" };
const amount: DesignerField = { table: "Trips", name: "Amount", kind: "column", dataType: "integer" };
const trips: DesignerField = { table: "Trips", name: "Trips", kind: "measure", dataType: "decimal" };

describe("wells", () => {
  it("fills a matching well and refuses a drop past the maximum", () => {
    const axis = visualSpec("column").wells.find((well) => well.name === "x-axis");
    const values = visualSpec("column").wells.find((well) => well.name === "y-axis");
    if (!axis || !values) throw new Error("missing wells");

    const first = dropField({}, axis, month);
    expect(first.accepted).toBe(true);
    expect(first.wells["x-axis"]).toEqual([{ table: "Trips", column: "Month" }]);

    const second = dropField(first.wells, axis, month);
    expect(second.accepted).toBe(false);
    expect(second.wells).toBe(first.wells);

    const measure = dropField({}, values, trips);
    expect(measure.wells["y-axis"]).toEqual([{ table: "Trips", measure: "Trips" }]);

    const summed = dropField({}, values, amount);
    expect(summed.wells["y-axis"]?.[0]?.aggregation).toBe("sum");

    expect(dropField({}, values, month).accepted).toBe(false);
  });
});
