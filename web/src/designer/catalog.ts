/** Visual gallery. Six types draw a query; the rest stay in the gallery without a fake chart. */

export interface WellSpec {
  name: string;
  displayName: string;
  kind: "grouping" | "measure" | "any";
  max: number;
}

export interface VisualSpec {
  type: string;
  displayName: string;
  abbr: string;
  icon: string;
  renders: "cartesian" | "pie" | "card" | "table" | "map" | "slicer" | "scatter" | "funnel" | "gauge" | "treemap" | "waterfall" | "none";
  orientation?: "column" | "bar" | "line";
  wells: WellSpec[];
}

const ICONS: Record<string, string> = {
  column: "M3 12h4v9H3v-9zm7-8h4v17h-4V4zm7 5h4v12h-4V9z",
  bar: "M3 4h13v4H3V4zm0 6h18v4H3v-4zm0 6h9v4H3v-4z",
  line: "M3 19l6-8 4 3 8-11v16H3z",
  pie: "M12 2v10h10A10 10 0 1 1 12 2z",
  card: "M2 5h20v14H2V5zm2 2v2h16V7H4zm0 5v5h11v-5H4z",
  table: "M3 4h18v16H3V4zm2 2v3h6V6H5zm8 0v3h6V6h-6zM5 11v3h6v-3H5zm8 0v3h6v-3h-6zM5 16v2h6v-2H5zm8 0v2h6v-2h-6z",
  map: "M12 2C8.1 2 5 5.1 5 9c0 5.2 7 13 7 13s7-7.8 7-13c0-3.9-3.1-7-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z",
  slicer: "M4 5h16v3H4V5zm0 5.5h16v3H4v-3zM4 16h10v3H4v-3z",
  scatter: "M6 16a2.2 2.2 0 1 0 .01 0zM13 9a2.2 2.2 0 1 0 .01 0zM19 5a2.2 2.2 0 1 0 .01 0zM8 7a1.8 1.8 0 1 0 .01 0zM16 14a1.8 1.8 0 1 0 .01 0z",
  funnel: "M2 3h20l-5 7H7L2 3zm5 8h10l-2.5 5h-5L7 11zm2.5 6h5L13.5 21h-3z",
  gauge: "M12 3a9 9 0 0 0-9 15h4.2A5.5 5.5 0 1 1 17 14.5L20.2 18A9 9 0 0 0 12 3zm1 7.2 4.2 4.8-1.5 1.3-4.7-5.3V7h2z",
  treemap: "M2 2h12v12H2V2zm14 0h6v7h-6V2zm0 9h6v11h-6V11zM2 16h12v6H2v-6z",
  waterfall: "M2 20V8h4v12H2zm6 0v-6h4v6H8zm6 0V4h4v16h-4zm6 0v-9h4v9h-4z",
};

const axisWells: WellSpec[] = [
  { name: "y-axis", displayName: "Y-axis", kind: "measure", max: 4 },
  { name: "x-axis", displayName: "X-axis", kind: "grouping", max: 1 },
  { name: "legend", displayName: "Legend", kind: "grouping", max: 1 },
];

function spec(type: string, displayName: string, abbr: string, extra: Partial<VisualSpec>): VisualSpec {
  return { type, displayName, abbr, icon: ICONS[type] ?? "", renders: "none", wells: axisWells, ...extra };
}

export const VISUALS: VisualSpec[] = [
  spec("column", "Column", "Co", { renders: "cartesian", orientation: "column" }),
  spec("bar", "Bar", "Ba", { renders: "cartesian", orientation: "bar" }),
  spec("line", "Line", "Li", { renders: "cartesian", orientation: "line" }),
  spec("pie", "Pie", "Pi", {
    renders: "pie",
    wells: [
      { name: "y-axis", displayName: "Y-axis", kind: "measure", max: 1 },
      { name: "x-axis", displayName: "X-axis", kind: "grouping", max: 1 },
    ],
  }),
  spec("card", "Card", "Ca", {
    renders: "card",
    wells: [{ name: "y-axis", displayName: "Y-axis", kind: "measure", max: 1 }],
  }),
  spec("table", "Table", "Ta", {
    renders: "table",
    wells: [{ name: "columns", displayName: "Columns", kind: "any", max: 8 }],
  }),
  spec("map", "Map", "Ma", { renders: "map", wells: [] }),
  spec("slicer", "Slicer", "Sl", {
    renders: "slicer",
    wells: [{ name: "field", displayName: "Field", kind: "grouping", max: 1 }],
  }),
  spec("scatter", "Scatter", "Sc", {
    renders: "scatter",
    wells: [
      { name: "x-axis", displayName: "X-axis", kind: "measure", max: 1 },
      { name: "y-axis", displayName: "Y-axis", kind: "measure", max: 1 },
      { name: "legend", displayName: "Legend", kind: "grouping", max: 1 },
    ],
  }),
  spec("funnel", "Funnel", "Fu", {
    renders: "funnel",
    wells: [
      { name: "y-axis", displayName: "Values", kind: "measure", max: 1 },
      { name: "x-axis", displayName: "Category", kind: "grouping", max: 1 },
    ],
  }),
  spec("gauge", "Gauge", "Ga", {
    renders: "gauge",
    wells: [{ name: "y-axis", displayName: "Value", kind: "measure", max: 1 }],
  }),
  spec("treemap", "Treemap", "Tr", {
    renders: "treemap",
    wells: [
      { name: "y-axis", displayName: "Values", kind: "measure", max: 1 },
      { name: "x-axis", displayName: "Category", kind: "grouping", max: 1 },
    ],
  }),
  spec("waterfall", "Waterfall", "Wa", {
    renders: "waterfall",
    wells: [
      { name: "y-axis", displayName: "Y-axis", kind: "measure", max: 1 },
      { name: "x-axis", displayName: "X-axis", kind: "grouping", max: 1 },
    ],
  }),
];

export function visualSpec(type: string): VisualSpec {
  return VISUALS.find((spec) => spec.type === type) ?? VISUALS[VISUALS.length - 1];
}
