import type { ThemeLayer } from "../shared/theme";

/** Report definition JSON contract. */

export interface ReportDefinition {
  schemaVersion: string;
  name: string;
  datasetId: string;
  pages: PageDefinition[];
  theme?: ThemeOverrides;
  filters?: FilterDefinition[];
  bookmarks?: BookmarkDefinition[];
}

export interface BookmarkDefinition {
  id: string;
  name: string;
  pageIndex: number;
  filters: FilterDefinition[];
  hiddenVisualIds: string[];
}

export interface PageDefinition {
  name: string;
  displayName: string;
  width: number;
  height: number;
  visuals: VisualDefinition[];
  filters?: FilterDefinition[];
  pageType?: "regular" | "drillthrough";
  drillthroughFilters?: FilterDefinition[];
  /** Where each visual sits on a phone (360 px wide). Visuals it leaves out aren't shown on a phone. */
  phone?: PhoneLayout;
}

export interface PhoneLayout {
  visuals: PhonePosition[];
}

export interface PhonePosition {
  /** The visual's id on this page. */
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
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

/** A built-in theme by id, plus this report's own changes to it. */
export interface ThemeOverrides {
  id?: string;
  colors?: string[];
  font?: string;
  background?: string;
  /** Anything else changed with "Customize current theme" or an imported theme file. */
  overrides?: ThemeLayer;
}
