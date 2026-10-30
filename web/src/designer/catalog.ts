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
  column: "M4 18V8h3v10H4zm5 0V4h3v14H9zm5 0v-7h3v7h-3z",
  bar: "M2 4h10v3H2V4zm0 5h14v3H2V9zm0 5h7v3H2v-3z",
  line: "M3 17l5-6 4 3 5-8",
  pie: "M11 2a9 9 0 110 18 9 9 0 010-18zm1 1v8h8a8 8 0 00-8-8z",
  card: "M3 5h14v10H3V5zm2 2v2h10V7H5zm0 4v2h6v-2H5z",
  table: "M3 4h14v12H3V4zm0 4h14M3 8h14M3 12h14M8 4v12",
  map: "M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5a2.5 2.5 0 110-5 2.5 2.5 0 010 5z",
  slicer: "M3 5h14v2H3V5zm0 4h14v2H3V9zm0 4h8v2H3v-2z",
  scatter: "M7 14a1.5 1.5 0 110 3 1.5 1.5 0 010-3zm4-5a1.5 1.5 0 110 3 1.5 1.5 0 010-3zm5-4a1.5 1.5 0 110 3 1.5 1.5 0 010-3zm-8 1a1.5 1.5 0 110 3 1.5 1.5 0 010-3zm6 6a1.5 1.5 0 110 3 1.5 1.5 0 010-3z",
  funnel: "M3 3h14l-3 5h-8L3 3zm3 6h8l-2 4H8L6 9zm2 5h4l-1 3h-2l-1-3z",
  gauge: "M12 2a10 10 0 00-8.66 15h17.32A10 10 0 0012 2zm0 4a6 6 0 014.47 10H7.53A6 6 0 0112 6zm0 3v4",
  treemap: "M3 3h8v8H3V3zm10 0h4v4h-4V3zm0 5h4v6h-4V8zM3 12h8v5H3v-5z",
  waterfall: "M4 18V8h2v10H4zm4 0v-4h2v4H8zm4 0V6h2v12h-2zm4 0v-8h2v8h-2z",
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
