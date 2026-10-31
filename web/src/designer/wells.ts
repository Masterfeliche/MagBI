/** Drop a field into a well, or refuse it when the well is full or the kind does not match. */

import type { FieldBinding } from "../types/report";
import type { VisualSpec, WellSpec } from "./catalog";
import { isNumeric, type DesignerField } from "./model";
import { bindingFor } from "./query";

const MEASURE_WELLS = ["y-axis", "values", "line", "columns", "field", "x-axis", "legend"];
const GROUP_WELLS = ["x-axis", "rows", "legend", "columns", "field", "y-axis"];

/** The well a field lands in when it is dropped on the visual itself. */
export function wellForDrop(
  spec: VisualSpec,
  field: DesignerField,
  wells: Record<string, FieldBinding[]>,
): WellSpec | null {
  const numeric = field.kind === "measure" || isNumeric(field.dataType);
  const order = numeric ? MEASURE_WELLS : GROUP_WELLS;
  for (const name of order) {
    const well = spec.wells.find((item) => item.name === name);
    if (!well) continue;
    if (dropField(wells, well, field).accepted) return well;
  }
  return null;
}

export function removeBinding(
  wells: Record<string, FieldBinding[]>,
  wellName: string,
  index: number,
): Record<string, FieldBinding[]> {
  return {
    ...wells,
    [wellName]: (wells[wellName] ?? []).filter((_, item) => item !== index),
  };
}

export function dropField(
  wells: Record<string, FieldBinding[]>,
  well: WellSpec,
  field: DesignerField,
): { wells: Record<string, FieldBinding[]>; accepted: boolean } {
  const current = wells[well.name] ?? [];
  if (current.length >= well.max) return { wells, accepted: false };
  if (well.kind === "grouping" && field.kind === "measure") return { wells, accepted: false };
  if (well.kind === "measure" && field.kind === "column" && !isNumeric(field.dataType)) {
    return { wells, accepted: false };
  }
  const placed: FieldBinding =
    well.kind === "grouping" ? { table: field.table, column: field.name } : bindingFor(field);
  return { wells: { ...wells, [well.name]: [...current, placed] }, accepted: true };
}
