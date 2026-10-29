/** Drop a field into a well, or refuse it when the well is full or the kind does not match. */

import type { FieldBinding } from "../types/report";
import type { WellSpec } from "./catalog";
import { isNumeric, type DesignerField } from "./model";
import { bindingFor } from "./query";

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
