/** Dataset definition JSON contract. */

export interface DatasetDefinition {
  schemaVersion: string;
  name: string;
  tables: TableDefinition[];
  relationships: RelationshipDefinition[];
  measures: MeasureDefinition[];
  roles?: RlsRoleDefinition[];
}

export interface TableDefinition {
  name: string;
  source: TableSource;
  columns: ColumnDefinition[];
  isDateTable?: boolean;
}

export type TableSource =
  | { type: "sqlTable"; schema: string; table: string }
  | { type: "sqlQuery"; query: string }
  | { type: "csv"; filePath: string };

export interface ColumnDefinition {
  name: string;
  dataType: "string" | "integer" | "decimal" | "boolean" | "dateTime" | "date" | "time" | "binary";
  isHidden?: boolean;
  sortByColumn?: string;
}

export interface MeasureDefinition {
  name: string;
  table: string;
  expression: string;
  formatString?: string;
  description?: string;
}

export interface RelationshipDefinition {
  fromTable: string;
  fromColumn: string;
  toTable: string;
  toColumn: string;
  cardinality: "manyToOne" | "oneToOne";
  crossFilterDirection: "single" | "both";
  isActive: boolean;
  joinType: "inner" | "left";
}

export interface RlsRoleDefinition {
  name: string;
  filters: Array<{
    table: string;
    expression: string;
  }>;
}
