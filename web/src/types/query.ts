/** Semantic query and DSR response contracts. */

export interface SemanticQuery {
  from: QuerySource[];
  select: QuerySelect[];
  where?: QueryFilter[];
  orderBy?: QueryOrderBy[];
  limit?: number;
  includeTotals?: boolean;
}

export interface QuerySource {
  table: string;
  as?: string;
}

export interface QuerySelect {
  column?: { table: string; column: string };
  measure?: { table: string; measure: string };
  aggregation?: string;
  as?: string;
}

export interface QueryFilter {
  column: { table: string; column: string };
  operator: "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "in" | "notIn" | "contains" | "startsWith" | "isBlank" | "isNotBlank";
  values?: unknown[];
}

export interface QueryOrderBy {
  select: number;
  direction: "asc" | "desc";
}

/** DataShapeResult — columnar JSON response. */
export interface DSR {
  columns: DSRColumn[];
  rows: unknown[][];
  rowCount: number;
  totals?: unknown[] | null;
  truncated?: boolean;
}

export interface DSRColumn {
  name: string;
  dataType: string;
  isMeasure: boolean;
  format?: string | null;
}
