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
  renders: "cartesian" | "pie" | "card" | "table" | "map" | "slicer" | "none";
  orientation?: "column" | "bar" | "line";
  wells: WellSpec[];
}

const axisWells: WellSpec[] = [
  { name: "y-axis", displayName: "Y-axis", kind: "measure", max: 4 },
  { name: "x-axis", displayName: "X-axis", kind: "grouping", max: 1 },
  { name: "legend", displayName: "Legend", kind: "grouping", max: 1 },
];

export const VISUALS: VisualSpec[] = [
  { type: "column", displayName: "Column", renders: "cartesian", orientation: "column", wells: axisWells },
  { type: "bar", displayName: "Bar", renders: "cartesian", orientation: "bar", wells: axisWells },
  { type: "line", displayName: "Line", renders: "cartesian", orientation: "line", wells: axisWells },
  {
    type: "pie",
    displayName: "Pie",
    renders: "pie",
    wells: [
      { name: "y-axis", displayName: "Y-axis", kind: "measure", max: 1 },
      { name: "x-axis", displayName: "X-axis", kind: "grouping", max: 1 },
    ],
  },
  {
    type: "card",
    displayName: "Card",
    renders: "card",
    wells: [{ name: "y-axis", displayName: "Y-axis", kind: "measure", max: 1 }],
  },
  {
    type: "table",
    displayName: "Table",
    renders: "table",
    wells: [{ name: "columns", displayName: "Columns", kind: "any", max: 8 }],
  },
  {
    type: "map",
    displayName: "Map",
    renders: "map",
    wells: [],
  },
  {
    type: "slicer",
    displayName: "Slicer",
    renders: "slicer",
    wells: [{ name: "field", displayName: "Field", kind: "grouping", max: 1 }],
  },
  { type: "scatter", displayName: "Scatter", renders: "none", wells: axisWells },
  { type: "funnel", displayName: "Funnel", renders: "none", wells: axisWells },
  { type: "gauge", displayName: "Gauge", renders: "none", wells: axisWells },
  { type: "treemap", displayName: "Treemap", renders: "none", wells: axisWells },
  { type: "waterfall", displayName: "Waterfall", renders: "none", wells: axisWells },
];

export function visualSpec(type: string): VisualSpec {
  return VISUALS.find((spec) => spec.type === type) ?? VISUALS[VISUALS.length - 1];
}
