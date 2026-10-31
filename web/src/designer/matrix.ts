/**
 * The matrix visual's data: rows in a hierarchy, an optional column field, and
 * values. Every subtotal and total comes from its own query at that level, as
 * in Power BI, so ratios and distinct counts are right at every level instead
 * of being added up.
 */

import type { DSR } from "../types/query";
import type { FieldBinding, FilterDefinition } from "../types/report";
import { whereClauses, type SemanticQueryBody } from "./query";

export const TOTAL = "\u0000total";

export interface MatrixLevel {
  /** How many row fields this answer is grouped by (0 = grand total). */
  depth: number;
  /** Whether it is also grouped by the column field. */
  byColumn: boolean;
}

export interface MatrixNode {
  /** Labels from the top level down to this row. */
  path: string[];
  label: string;
  depth: number;
  /** Values per column key (TOTAL for the row total), one per measure. */
  cells: Map<string, unknown[]>;
  children: MatrixNode[];
}

export interface Matrix {
  columns: string[];
  measures: { name: string; format: string | null }[];
  rows: MatrixNode[];
  total: Map<string, unknown[]>;
}

function select(binding: FieldBinding): SemanticQueryBody["select"][number] {
  if (binding.measure) return { measure: { table: binding.table, measure: binding.measure } };
  if (binding.aggregation) return { column: { table: binding.table, column: binding.column ?? "" }, aggregation: binding.aggregation };
  return { column: { table: binding.table, column: binding.column ?? "" } };
}

/** One query per level the matrix shows: each row depth, with and without the column field. */
export function matrixQueries(
  wells: Record<string, FieldBinding[]>,
  filters: FilterDefinition[],
): { level: MatrixLevel; query: SemanticQueryBody }[] {
  const rows = wells.rows ?? [];
  const column = (wells.columns ?? [])[0];
  const values = wells.values ?? [];
  if (values.length === 0 || (rows.length === 0 && !column)) return [];
  const where = whereClauses(filters);
  const out: { level: MatrixLevel; query: SemanticQueryBody }[] = [];
  for (let depth = 0; depth <= rows.length; depth += 1) {
    for (const byColumn of column ? [false, true] : [false]) {
      const fields = [...rows.slice(0, depth), ...(byColumn && column ? [column] : []), ...values];
      out.push({
        level: { depth, byColumn },
        query: { from: [], select: fields.map(select), ...(where.length ? { where } : {}) },
      });
    }
  }
  return out;
}

// A blank member reads "Not set", MagBI's no-data label, never "(Blank)".
const text = (value: unknown) => (value == null || value === "" ? "Not set" : String(value));

/** Builds the row tree from the answers to ``matrixQueries``. */
export function buildMatrix(answers: { level: MatrixLevel; dsr: DSR }[], rowCount: number, hasColumn: boolean): Matrix {
  const deepest = answers.find((item) => item.level.depth === rowCount && !item.level.byColumn) ?? answers[0];
  const valueCount = deepest ? deepest.dsr.columns.filter((column) => column.isMeasure).length : 0;
  const measures = deepest
    ? deepest.dsr.columns.filter((column) => column.isMeasure).map((column) => ({ name: column.name, format: column.format ?? null }))
    : [];
  const columns = hasColumn
    ? [...new Set(answers.filter((item) => item.level.byColumn).flatMap((item) => item.dsr.rows.map((row) => text(row[item.level.depth]))))].sort(
        (a, b) => a.localeCompare(b, undefined, { numeric: true }),
      )
    : [];
  const nodes = new Map<string, MatrixNode>();
  const total = new Map<string, unknown[]>();
  const keyOf = (path: string[]) => path.join("\u0001");

  for (const { level, dsr } of [...answers].sort((a, b) => a.level.depth - b.level.depth)) {
    for (const row of dsr.rows) {
      const path = row.slice(0, level.depth).map(text);
      const columnKey = level.byColumn ? text(row[level.depth]) : TOTAL;
      const values = row.slice(row.length - valueCount);
      if (level.depth === 0) {
        total.set(columnKey, values);
        continue;
      }
      const key = keyOf(path);
      let node = nodes.get(key);
      if (!node) {
        node = { path, label: path[path.length - 1] ?? "", depth: level.depth - 1, cells: new Map(), children: [] };
        nodes.set(key, node);
        const parent = level.depth > 1 ? nodes.get(keyOf(path.slice(0, -1))) : undefined;
        parent?.children.push(node);
      }
      node.cells.set(columnKey, values);
    }
  }
  const order = (list: MatrixNode[]) => {
    list.sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true }));
    list.forEach((node) => order(node.children));
    return list;
  };
  const rows = order([...nodes.values()].filter((node) => node.depth === 0));
  return { columns, measures, rows, total };
}

/** The rows to show, top to bottom, given which paths are expanded. */
export function visibleRows(rows: MatrixNode[], expanded: Set<string>): MatrixNode[] {
  const out: MatrixNode[] = [];
  const walk = (list: MatrixNode[]) => {
    for (const node of list) {
      out.push(node);
      if (node.children.length > 0 && expanded.has(node.path.join("\u0001"))) walk(node.children);
    }
  };
  walk(rows);
  return out;
}

/** Every path that has children, for "Expand all". */
export function expandablePaths(rows: MatrixNode[]): string[] {
  const out: string[] = [];
  const walk = (list: MatrixNode[]) => {
    for (const node of list) {
      if (node.children.length > 0) {
        out.push(node.path.join("\u0001"));
        walk(node.children);
      }
    }
  };
  walk(rows);
  return out;
}
