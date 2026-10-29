/** Report definition JSON contract. */

export interface ReportDefinition {
  schemaVersion: string;
  name: string;
  datasetId: string;
  pages: PageDefinition[];
  theme?: ThemeOverrides;
  filters?: FilterDefinition[];
}

export interface PageDefinition {
  name: string;
  displayName: string;
  width: number;
  height: number;
  visuals: VisualDefinition[];
  filters?: FilterDefinition[];
}

export interface VisualDefinition {
  id: string;
  type: string;
  x: number;
  y: number;
  width: number;
  height: number;
  wells: Record<string, FieldBinding[]>;
  properties?: Record<string, unknown>;
  filters?: FilterDefinition[];
  interactions?: InteractionConfig;
}

export interface FieldBinding {
  table: string;
  column?: string;
  measure?: string;
  aggregation?: "sum" | "count" | "average" | "min" | "max" | "distinctCount";
}

export interface FilterDefinition {
  table: string;
  column: string;
  type: "basic" | "advanced" | "topN" | "relativeDate";
  config: unknown;
}

export interface InteractionConfig {
  source: string;
  targets: Record<string, "crossFilter" | "crossHighlight" | "none">;
}

export interface ThemeOverrides {
  colors?: string[];
  font?: string;
  background?: string;
}
