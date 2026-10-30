import type { FilterDefinition } from "../types/report";

export type SlicerMode = "list" | "dropdown" | "range";

export function slicerFilters(
  table: string,
  column: string,
  mode: SlicerMode,
  selected: string[],
  range?: { min: string; max: string },
): FilterDefinition[] {
  if (mode === "range") {
    const filters: FilterDefinition[] = [];
    if (range?.min) {
      filters.push({
        table,
        column,
        type: "basic",
        config: { operator: "gte", values: [range.min] },
      });
    }
    if (range?.max) {
      filters.push({
        table,
        column,
        type: "basic",
        config: { operator: "lte", values: [range.max] },
      });
    }
    return filters;
  }
  if (selected.length === 0) return [];
  return [
    {
      table,
      column,
      type: "basic",
      config: { operator: "in", values: selected },
    },
  ];
}
