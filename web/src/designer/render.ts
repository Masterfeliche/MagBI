/** Turn a DSR into a chart, card, or table. Other gallery types do not borrow a column chart. */

import type { DSR } from "../types/query";
import { visualSpec } from "./catalog";

export interface CartesianModel {
  kind: "cartesian";
  orientation: "column" | "bar" | "line";
  categories: string[];
  series: { name: string; values: number[] }[];
}

export interface PieModel {
  kind: "pie";
  slices: { name: string; value: number }[];
}

export interface CardModel {
  kind: "card";
  value: string;
}

export interface TableModel {
  kind: "table";
  columns: string[];
  rows: string[][];
}

export interface ScatterModel {
  kind: "scatter";
  series: { name: string; data: [number, number][] }[];
}

export interface FunnelModel {
  kind: "funnel";
  items: { name: string; value: number }[];
}

export interface GaugeModel {
  kind: "gauge";
  value: number;
  name: string;
}

export interface TreemapModel {
  kind: "treemap";
  items: { name: string; value: number }[];
}

export interface WaterfallModel {
  kind: "waterfall";
  categories: string[];
  values: number[];
}

export interface NoteModel {
  kind: "note";
  message: string;
}

export type RenderModel =
  | CartesianModel | PieModel | CardModel | TableModel
  | ScatterModel | FunnelModel | GaugeModel | TreemapModel | WaterfallModel
  | NoteModel;

export function renderModel(type: string, dsr: DSR | null): RenderModel {
  const spec = visualSpec(type);
  if (spec.renders === "map") {
    return { kind: "note", message: "This map needs latitude and longitude." };
  }
  if (spec.renders === "none" || spec.renders === "slicer") {
    return { kind: "note", message: "This visual is not drawn as a chart." };
  }
  if (!dsr || dsr.rows.length === 0) {
    return { kind: "note", message: "Add fields to run a query." };
  }
  if (spec.renders === "card") return { kind: "card", value: text(firstMeasure(dsr)) };
  if (spec.renders === "table") {
    return {
      kind: "table",
      columns: dsr.columns.map((column) => column.name),
      rows: dsr.rows.map((row) => row.map((cell) => text(cell))),
    };
  }
  if (spec.renders === "pie") return pie(dsr);
  if (spec.renders === "scatter") return scatter(dsr);
  if (spec.renders === "funnel") return funnelModel(dsr);
  if (spec.renders === "gauge") return gaugeModel(dsr);
  if (spec.renders === "treemap") return treemapModel(dsr);
  if (spec.renders === "waterfall") return waterfallModel(dsr);
  return cartesian(dsr, spec.orientation ?? "column");
}

function cartesian(dsr: DSR, orientation: "column" | "bar" | "line"): CartesianModel {
  const measures = indexes(dsr, true);
  const groups = indexes(dsr, false);
  const categoryIndex = groups[0];
  const legendIndex = groups[1];
  if (categoryIndex === undefined) {
    return {
      kind: "cartesian",
      orientation,
      categories: dsr.rows.map((_, index) => String(index + 1)),
      series: seriesFrom(dsr, measures),
    };
  }
  if (legendIndex === undefined) {
    const ordered = orderMonths(
      dsr.rows.map((row) => text(row[categoryIndex])),
      seriesFrom(dsr, measures),
    );
    return { kind: "cartesian", orientation, ...ordered };
  }
  const categories = unique(dsr.rows.map((row) => text(row[categoryIndex])));
  const legends = unique(dsr.rows.map((row) => text(row[legendIndex])));
  const measure = measures[0];
  return {
    kind: "cartesian",
    orientation,
    categories,
    series: legends.map((legend) => ({
      name: legend,
      values: categories.map((category) => {
        const row = dsr.rows.find(
          (item) => text(item[categoryIndex]) === category && text(item[legendIndex]) === legend,
        );
        return row && measure !== undefined ? number(row[measure]) : 0;
      }),
    })),
  };
}

function pie(dsr: DSR): PieModel {
  const groups = indexes(dsr, false);
  const measures = indexes(dsr, true);
  const categoryIndex = groups[0];
  const measure = measures[0];
  return {
    kind: "pie",
    slices: dsr.rows.map((row, index) => ({
      name: categoryIndex === undefined ? String(index + 1) : text(row[categoryIndex]),
      value: measure === undefined ? 0 : number(row[measure]),
    })),
  };
}

function scatter(dsr: DSR): ScatterModel {
  const measures = indexes(dsr, true);
  const groups = indexes(dsr, false);
  const xIdx = measures[0];
  const yIdx = measures[1] ?? measures[0];
  if (xIdx === undefined) return { kind: "scatter", series: [] };
  if (groups[0] === undefined) {
    return {
      kind: "scatter",
      series: [{ name: "Series", data: dsr.rows.map((row) => [number(row[xIdx]), number(row[yIdx])]) }],
    };
  }
  const legends = unique(dsr.rows.map((row) => text(row[groups[0]!])));
  return {
    kind: "scatter",
    series: legends.map((legend) => ({
      name: legend,
      data: dsr.rows
        .filter((row) => text(row[groups[0]!]) === legend)
        .map((row) => [number(row[xIdx]), number(row[yIdx])]),
    })),
  };
}

function funnelModel(dsr: DSR): FunnelModel {
  const result = pie(dsr);
  return { kind: "funnel", items: result.slices };
}

function gaugeModel(dsr: DSR): GaugeModel {
  const measureIdx = dsr.columns.findIndex((c) => c.isMeasure);
  const idx = measureIdx >= 0 ? measureIdx : 0;
  return { kind: "gauge", value: number(dsr.rows[0]?.[idx]), name: dsr.columns[idx]?.name ?? "Value" };
}

function treemapModel(dsr: DSR): TreemapModel {
  const result = pie(dsr);
  return { kind: "treemap", items: result.slices.map((s) => ({ name: s.name, value: s.value })) };
}

function waterfallModel(dsr: DSR): WaterfallModel {
  const groups = indexes(dsr, false);
  const measures = indexes(dsr, true);
  const categoryIdx = groups[0];
  const measureIdx = measures[0];
  if (measureIdx === undefined) return { kind: "waterfall", categories: [], values: [] };
  return {
    kind: "waterfall",
    categories: dsr.rows.map((row, i) => (categoryIdx !== undefined ? text(row[categoryIdx]) : String(i + 1))),
    values: dsr.rows.map((row) => number(row[measureIdx])),
  };
}

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

function orderMonths(
  categories: string[],
  series: { name: string; values: number[] }[],
): { categories: string[]; series: { name: string; values: number[] }[] } {
  const indexes = categories.map((category) => MONTHS.indexOf(category.slice(0, 3).toLowerCase()));
  if (indexes.some((index) => index < 0)) return { categories, series };
  const order = categories.map((_, index) => index).sort((a, b) => indexes[a] - indexes[b]);
  return {
    categories: order.map((index) => categories[index]),
    series: series.map((item) => ({
      name: item.name,
      values: order.map((index) => item.values[index] ?? 0),
    })),
  };
}

function seriesFrom(dsr: DSR, measures: number[]): { name: string; values: number[] }[] {
  return measures.map((index) => ({
    name: dsr.columns[index]?.name ?? "Value",
    values: dsr.rows.map((row) => number(row[index])),
  }));
}

function firstMeasure(dsr: DSR): unknown {
  const index = dsr.columns.findIndex((column) => column.isMeasure);
  const column = index >= 0 ? index : 0;
  return dsr.rows[0]?.[column];
}

function indexes(dsr: DSR, measure: boolean): number[] {
  return dsr.columns.flatMap((column, index) => (column.isMeasure === measure ? [index] : []));
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}

function number(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function text(value: unknown): string {
  return value == null ? "" : String(value);
}
