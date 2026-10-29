/** Build a Sprint 5 semantic query from a visual's wells and page filters. */

import type { FieldBinding, FilterDefinition } from "../types/report";
import { isNumeric, type DesignerField } from "./model";

export interface SemanticQueryBody {
  from: [];
  select: Array<
    | { column: { table: string; column: string }; aggregation?: string }
    | { measure: { table: string; measure: string } }
  >;
  where?: Array<{
    column: { table: string; column: string };
    operator: "eq" | "in";
    values: unknown[];
  }>;
}

export function bindingFor(field: DesignerField): FieldBinding {
  if (field.kind === "measure") {
    return { table: field.table, measure: field.name };
  }
  if (isNumeric(field.dataType)) {
    return { table: field.table, column: field.name, aggregation: "sum" };
  }
  return { table: field.table, column: field.name };
}

export function buildQuery(
  wells: Record<string, FieldBinding[]>,
  filters: FilterDefinition[] = [],
): SemanticQueryBody {
  const select: SemanticQueryBody["select"] = [];
  for (const binding of [...(wells["x-axis"] ?? []), ...(wells["y-axis"] ?? [])]) {
    if (binding.measure) {
      select.push({ measure: { table: binding.table, measure: binding.measure } });
      continue;
    }
    if (!binding.column) continue;
    if (binding.aggregation) {
      select.push({
        column: { table: binding.table, column: binding.column },
        aggregation: binding.aggregation,
      });
      continue;
    }
    select.push({ column: { table: binding.table, column: binding.column } });
  }
  const where = filters.flatMap((filter) => {
    if (filter.type !== "basic" || !filter.config || typeof filter.config !== "object") {
      return [];
    }
    const config = filter.config as { operator?: string; values?: unknown[] };
    const operator = config.operator === "in" ? "in" : "eq";
    const values = Array.isArray(config.values) ? config.values : [];
    if (values.length === 0) return [];
    return [
      {
        column: { table: filter.table, column: filter.column },
        operator,
        values,
      } as const,
    ];
  });
  return where.length > 0 ? { from: [], select, where } : { from: [], select };
}
