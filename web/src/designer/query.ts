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
    operator: "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "in" | "contains" | "startsWith";
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
  options: { drillLevel?: number } = {},
): SemanticQueryBody {
  const select: SemanticQueryBody["select"] = [];
  const hierarchy = wells.hierarchy ?? [];
  const level = options.drillLevel ?? 0;
  const xAxis = hierarchy[level] ? [hierarchy[level]] : wells["x-axis"] ?? [];
  const ordered = [
    ...xAxis,
    ...(wells.legend ?? []),
    ...(wells["y-axis"] ?? []),
    ...(wells.columns ?? []),
    ...(wells.tooltips ?? []),
  ];
  for (const binding of ordered) {
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
  const where = whereClauses(filters);
  return where.length > 0 ? { from: [], select, where } : { from: [], select };
}

/** Basic filters as semantic WHERE entries. A filter with no values is left out. */
export function whereClauses(filters: FilterDefinition[]): NonNullable<SemanticQueryBody["where"]> {
  return filters.flatMap((filter) => {
    if (filter.type !== "basic" || !filter.config || typeof filter.config !== "object") {
      return [];
    }
    const config = filter.config as { operator?: string; values?: unknown[] };
    const allowed = ["eq", "ne", "gt", "gte", "lt", "lte", "in", "contains", "startsWith"] as const;
    const operator = allowed.find((item) => item === config.operator) ?? "eq";
    const values = Array.isArray(config.values) ? config.values : [];
    if (values.length === 0) return [];
    return [{ column: { table: filter.table, column: filter.column }, operator, values }];
  });
}
