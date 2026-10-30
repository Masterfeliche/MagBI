/** Page filters, one cross-filter, and the title/color patch. */

import type { FilterDefinition, VisualDefinition } from "../types/report";

export interface CrossFilter {
  sourceId: string;
  table: string;
  column: string;
  value: string;
}

export function toggleCrossFilter(
  current: CrossFilter | null,
  sourceId: string,
  table: string,
  column: string,
  value: string,
): CrossFilter | null {
  if (
    current &&
    current.sourceId === sourceId &&
    current.table === table &&
    current.column === column &&
    current.value === value
  ) {
    return null;
  }
  return { sourceId, table, column, value };
}

export function filtersForVisual(
  pageFilters: FilterDefinition[],
  cross: CrossFilter | null,
  visualId: string,
  applyCross = true,
): FilterDefinition[] {
  if (!applyCross || !cross || cross.sourceId === visualId) return pageFilters;
  return [
    ...pageFilters,
    {
      table: cross.table,
      column: cross.column,
      type: "basic",
      config: { operator: "eq", values: [cross.value] },
    },
  ];
}

export type FilterOperator = "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "in" | "contains" | "startsWith";

export function pageFilter(
  table: string,
  column: string,
  operator: FilterOperator,
  raw: string,
): FilterDefinition {
  const values =
    operator === "in"
      ? raw
          .split(",")
          .map((part) => part.trim())
          .filter((part) => part.length > 0)
      : [raw];
  return { table, column, type: "basic", config: { operator, values } };
}

export function categoryOpacity(category: string, highlight?: string): number {
  return !highlight || category === highlight ? 1 : 0.3;
}

export function groupingOf(visual: VisualDefinition): { table: string; column: string } | null {
  for (const name of ["x-axis", "columns", "field"]) {
    const binding = visual.wells[name]?.find((item) => item.column);
    if (binding?.column) return { table: binding.table, column: binding.column };
  }
  return null;
}

export function patchFormat(visual: VisualDefinition, title: string, color: string): VisualDefinition {
  return { ...visual, properties: { ...visual.properties, title, color } };
}
