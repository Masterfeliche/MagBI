/** Visual gallery. Every type draws: classic charts through the render models, the standard kit through KitVisual. */

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
  renders: "cartesian" | "pie" | "card" | "table" | "matrix" | "map" | "filledMap" | "slicer" | "scatter" | "funnel" | "gauge" | "treemap" | "waterfall" | "none";
  orientation?: "column" | "bar" | "line";
  /** Stacked series, or stacked to 100% of each category. */
  stack?: "stacked" | "percent";
  /** A line with the area under it filled. */
  area?: boolean;
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
  stackedColumn: "M3 13h4v8H3v-8zm0-5h4v4H3V8zm7 4h4v9h-4v-9zm0-8h4v7h-4V4zm7 6h4v11h-4V10zm0-4h4v3h-4V6z",
  stackedBar: "M3 4h8v4H3V4zm9 0h6v4h-6V4zM3 10h5v4H3v-4zm6 0h10v4H9v-4zM3 16h11v4H3v-4zm12 0h4v4h-4v-4z",
  column100: "M3 3h4v9H3V3zm0 10h4v8H3v-8zm7-10h4v5h-4V3zm0 6h4v12h-4V9zm7-6h4v13h-4V3zm0 14h4v4h-4v-4z",
  bar100: "M3 4h11v4H3V4zm12 0h6v4h-6V4zM3 10h6v4H3v-4zm7 0h11v4H10v-4zM3 16h15v4H3v-4zm16 0h2v4h-2v-4z",
  area: "M3 19l5-7 4 3 9-10v14H3z",
  stackedArea: "M3 21v-5l5-4 4 2 9-7v14H3zm0-8l5-6 4 3 9-8v3l-9 7-4-2-5 4v-1z",
  combo: "M3 13h4v8H3v-8zm7-4h4v12h-4V9zm7 6h4v6h-4v-6zM3 9l6-5 5 3 7-5 1 1.5-8 5.5-5-3-5 4.5L3 9z",
  matrix: "M3 3h18v18H3V3zm2 2v4h4V5H5zm6 0v4h8V5h-8zM5 11v8h4v-8H5zm6 0v3h8v-3h-8zm0 5v3h8v-3h-8z",
};

const axisWells: WellSpec[] = [
  { name: "y-axis", displayName: "Y-axis", kind: "measure", max: 4 },
  { name: "x-axis", displayName: "X-axis", kind: "grouping", max: 1 },
  { name: "legend", displayName: "Legend", kind: "grouping", max: 1 },
  { name: "hierarchy", displayName: "Hierarchy", kind: "grouping", max: 4 },
  { name: "tooltips", displayName: "Tooltips", kind: "any", max: 4 },
];

function spec(type: string, displayName: string, abbr: string, extra: Partial<VisualSpec>): VisualSpec {
  return { type, displayName, abbr, icon: ICONS[type] ?? "", renders: "none", wells: axisWells, ...extra };
}

export const VISUALS: VisualSpec[] = [
  spec("column", "Column", "Co", { renders: "cartesian", orientation: "column" }),
  spec("bar", "Bar", "Ba", { renders: "cartesian", orientation: "bar" }),
  spec("line", "Line", "Li", { renders: "cartesian", orientation: "line" }),
  spec("area", "Area", "Ar", { renders: "cartesian", orientation: "line", area: true }),
  spec("stackedArea", "Stacked area", "SA", { renders: "cartesian", orientation: "line", area: true, stack: "stacked" }),
  spec("stackedColumn", "Stacked column", "SC", { renders: "cartesian", orientation: "column", stack: "stacked" }),
  spec("stackedBar", "Stacked bar", "SB", { renders: "cartesian", orientation: "bar", stack: "stacked" }),
  spec("column100", "100% stacked column", "C%", { renders: "cartesian", orientation: "column", stack: "percent" }),
  spec("bar100", "100% stacked bar", "B%", { renders: "cartesian", orientation: "bar", stack: "percent" }),
  spec("combo", "Line and column", "LC", {
    renders: "cartesian",
    orientation: "column",
    // One value axis for both, so columns and lines are read on the same scale.
    wells: [
      { name: "x-axis", displayName: "X-axis", kind: "grouping", max: 1 },
      { name: "y-axis", displayName: "Column values", kind: "measure", max: 4 },
      { name: "line", displayName: "Line values", kind: "measure", max: 4 },
      { name: "tooltips", displayName: "Tooltips", kind: "any", max: 4 },
    ],
  }),
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
  spec("matrix", "Matrix", "Mx", {
    renders: "matrix",
    wells: [
      { name: "rows", displayName: "Rows", kind: "grouping", max: 3 },
      { name: "columns", displayName: "Columns", kind: "grouping", max: 1 },
      { name: "values", displayName: "Values", kind: "measure", max: 6 },
    ],
  }),
  spec("map", "Map", "Ma", {
    renders: "map",
    wells: [
      { name: "x-axis", displayName: "Location", kind: "grouping", max: 1 },
      { name: "latitude", displayName: "Latitude", kind: "grouping", max: 1 },
      { name: "longitude", displayName: "Longitude", kind: "grouping", max: 1 },
      { name: "y-axis", displayName: "Bubble size", kind: "measure", max: 1 },
    ],
  }),
  spec("filledMap", "Filled map", "FM", {
    renders: "filledMap",
    icon: "M4 4l6-2 5 3 5-2v16l-5 2-5-3-6 2V4zm6 0v13m5-12v13",
    wells: [
      { name: "x-axis", displayName: "Region", kind: "grouping", max: 1 },
      { name: "y-axis", displayName: "Value", kind: "measure", max: 1 },
    ],
  }),
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
  spec("kpi", "KPI card", "Kp", { renders: "none", icon: "M4 16h4v4H4v-4zm6-6h4v10h-4V10zm6-4h4v14h-4V6z", wells: [
    { name: "y-axis", displayName: "Value", kind: "measure", max: 1 },
    { name: "extra", displayName: "Context values", kind: "measure", max: 4 },
  ] }),
  spec("chain", "Stock-flow chain", "Ch", { renders: "none", icon: "M2 6h4v4H2V6zm6 0h4v4H8V6zm6 0h4v4h-4V6zm6 0h4v4h-4V6z", wells: [
    { name: "x-axis", displayName: "Stage", kind: "grouping", max: 1 },
    { name: "columns", displayName: "Order, unit, tones, age limit", kind: "grouping", max: 5 },
    { name: "y-axis", displayName: "Count, age, flags", kind: "measure", max: 3 },
  ] }),
  spec("calendar", "Period columns", "Pc", { renders: "none", icon: "M3 20h18v1.5H3V20zm1-6h3v5H4v-5zm4.5-4h3v9h-3v-9zm4.5 2h3v7h-3v-7zm4.5-6h3v13h-3V6z", wells: [
    { name: "x-axis", displayName: "Period label", kind: "grouping", max: 1 },
    { name: "columns", displayName: "Sort key and flag", kind: "grouping", max: 2 },
    { name: "y-axis", displayName: "Value", kind: "measure", max: 1 },
  ] }),
  spec("donut", "Donut", "Do", { renders: "none", icon: "M12 2a10 10 0 1 0 .01 0zM12 7a5 5 0 1 1 0 10 5 5 0 0 1 0-10z", wells: [
    { name: "x-axis", displayName: "Category", kind: "grouping", max: 1 },
    { name: "y-axis", displayName: "Value", kind: "measure", max: 1 },
    { name: "centre", displayName: "Centre value", kind: "measure", max: 1 },
  ] }),
  spec("pareto", "Pareto", "Pa", { renders: "none", icon: "M3 18h4V8H3v10zm6 0h4V4H9v14zm6 0h4v-7h-4v7zM3 20h18v2H3z", wells: [
    { name: "x-axis", displayName: "Category", kind: "grouping", max: 1 },
    { name: "y-axis", displayName: "Value", kind: "measure", max: 1 },
  ] }),
  spec("heatmap", "Heat matrix", "He", { renders: "none", icon: "M3 3h6v6H3V3zm8 0h6v6h-6V3zM3 11h6v6H3v-6zm8 0h6v6h-6v-6z", wells: [
    { name: "x-axis", displayName: "Rows", kind: "grouping", max: 1 },
    { name: "legend", displayName: "Columns", kind: "grouping", max: 1 },
    { name: "y-axis", displayName: "Value", kind: "measure", max: 1 },
  ] }),
  spec("grid", "Status table", "Gr", { renders: "none", icon: "M3 4h18v3H3V4zm0 5h11v3H3V9zm13 0h5v3h-5V9zM3 14h11v3H3v-3zm13 0h5v3h-5v-3zM3 19h11v2H3v-2z", wells: [{ name: "columns", displayName: "Columns", kind: "any", max: 12 }] }),
  spec("meter", "Target gauge", "Me", { renders: "none", icon: "M2 17a10 10 0 0 1 20 0h-3a7 7 0 0 0-14 0H2zm9.2-12h1.6v5h-1.6V5z", wells: [{ name: "y-axis", displayName: "Value", kind: "measure", max: 1 }] }),
  spec("bars", "Ranked bars", "Rb", { renders: "none", icon: "M3 3h1.5v18H3V3zm3 1h15v3.5H6V4zm0 5.5h11V13H6V9.5zM6 15h7v3.5H6V15z", wells: [
    { name: "x-axis", displayName: "Category (optional)", kind: "grouping", max: 1 },
    { name: "y-axis", displayName: "Values", kind: "measure", max: 6 },
  ] }),
  spec("stack100", "100% stacked bar", "St", { renders: "none", icon: "M3 5h12v5H3V5zm13 0h5v5h-5V5zM3 13h7v5H3v-5zm8 0h10v5H11v-5z", wells: [
    { name: "x-axis", displayName: "Category", kind: "grouping", max: 1 },
    { name: "legend", displayName: "Parts", kind: "grouping", max: 1 },
    { name: "y-axis", displayName: "Value", kind: "measure", max: 1 },
  ] }),
  spec("flow", "Stage flow", "Fl", { renders: "none", icon: "M3 4h18v3H3V4zm3 5h12v3H6V9zm3 5h6v3H9v-3zm2.2 5h1.6v2h-1.6v-2z", wells: [{ name: "y-axis", displayName: "Stages", kind: "measure", max: 6 }] }),
  spec("header", "Page header", "Hd", { renders: "none", icon: "M3 5h18v3H3V5zm0 6h12v3H3v-3zm0 6h8v3H3v-3z", wells: [] }),
  spec("label", "Label", "La", { renders: "none", icon: "M4 6h16v2H4V6zm0 5h10v2H4v-2z", wells: [] }),
  spec("frame", "Frame", "Fr", { renders: "none", icon: "M3 3h18v18H3V3zm2 2v14h14V5H5z", wells: [] }),
];

export function visualSpec(type: string): VisualSpec {
  return VISUALS.find((spec) => spec.type === type) ?? VISUALS[VISUALS.length - 1];
}
