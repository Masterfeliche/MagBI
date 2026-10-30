/** Queries for kit visuals: a fixed column order per type, so each visual knows its roles. */

import { whereClauses } from "../designer/query";
import type { QuerySelect, SemanticQuery } from "../types/query";
import type { FieldBinding, FilterDefinition, VisualDefinition } from "../types/report";

/** Wells in select order. A result column's position says which role it plays. */
export const KIT_ROLES: Record<string, string[]> = {
  kpi: ["y-axis", "extra"],
  chain: ["x-axis", "columns", "y-axis"],
  calendar: ["x-axis", "columns", "y-axis"],
  donut: ["x-axis", "y-axis"],
  pareto: ["x-axis", "y-axis"],
  heatmap: ["x-axis", "legend", "y-axis"],
  grid: ["columns"],
  meter: ["y-axis"],
  bars: ["x-axis", "y-axis"],
  stack100: ["x-axis", "legend", "y-axis"],
  flow: ["y-axis"],
  header: [],
  label: [],
  frame: [],
};

export function isKitType(type: string): boolean {
  return type in KIT_ROLES;
}

export function kitBindings(visual: VisualDefinition): FieldBinding[] {
  return (KIT_ROLES[visual.type] ?? []).flatMap((well) => visual.wells[well] ?? []);
}

function selectOf(binding: FieldBinding): QuerySelect | null {
  if (binding.measure) return { measure: { table: binding.table, measure: binding.measure } };
  if (!binding.column) return null;
  if (binding.aggregation) {
    return { column: { table: binding.table, column: binding.column }, aggregation: binding.aggregation };
  }
  return { column: { table: binding.table, column: binding.column } };
}

function isGroup(binding: FieldBinding): boolean {
  return !binding.measure && !binding.aggregation && Boolean(binding.column);
}

export interface KitOrder {
  select: number;
  direction: "asc" | "desc";
}

/** The visual's question, with its own filters, sort and row limit. */
export function kitQuery(visual: VisualDefinition, filters: FilterDefinition[]): SemanticQuery | null {
  const select = kitBindings(visual).map(selectOf).filter((item): item is QuerySelect => item !== null);
  if (select.length === 0) return null;
  const query: SemanticQuery = { from: [], select };
  const where = whereClauses(filters);
  if (where.length > 0) query.where = where;
  const orderBy = visual.properties?.orderBy;
  if (Array.isArray(orderBy) && orderBy.length > 0) query.orderBy = orderBy as KitOrder[];
  const limit = visual.properties?.limit;
  if (typeof limit === "number") query.limit = limit;
  return query;
}

/**
 * Every member of the visual's group columns, unfiltered: Power BI's
 * "show items with no data". Null when the visual does not ask for it.
 */
export function memberQuery(visual: VisualDefinition): SemanticQuery | null {
  if (!visual.properties?.allMembers) return null;
  const groups = kitBindings(visual).filter(isGroup);
  if (groups.length === 0) return null;
  return { from: [], select: groups.map(selectOf).filter((item): item is QuerySelect => item !== null) };
}

/**
 * Put member rows into the result: each member keeps its measures when the
 * filtered result has it, and gets nulls otherwise. Member order wins.
 */
export function mergeMembers(visual: VisualDefinition, rows: unknown[][], members: unknown[][]): unknown[][] {
  const bindings = kitBindings(visual);
  const groupAt = bindings.flatMap((binding, index) => (isGroup(binding) ? [index] : []));
  const key = (values: unknown[]) => JSON.stringify(values);
  const found = new Map(rows.map((row) => [key(groupAt.map((index) => row[index])), row]));
  return members.map((member) => {
    const hit = found.get(key(member));
    if (hit) return hit;
    const row: unknown[] = bindings.map(() => null);
    groupAt.forEach((index, offset) => {
      row[index] = member[offset];
    });
    return row;
  });
}
