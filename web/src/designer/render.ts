/** Turn a DSR into a chart, card, or table. Other gallery types do not borrow a column chart. */

import type { DSR } from "../types/query";
import { visualSpec } from "./catalog";
import { arrangeMonths } from "./period";

export interface CartesianModel {
  kind: "cartesian";
  orientation: "column" | "bar" | "line";
  categories: string[];
  series: { name: string; values: number[] }[];
  tooltips?: { name: string; values: string[] }[];
  /** Stacked series, or each category stacked to 100%. */
  stack?: "stacked" | "percent";
  area?: boolean;
  /** How many of the last series are drawn as lines (Line and column). */
  lineCount?: number;
}

export interface PieModel {
  kind: "pie";
  slices: { name: string; value: number }[];
}

export interface CardModel {
  kind: "card";
  /** The measure's format string, e.g. "#,0" or "0.0%". */
  format?: string | null;
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

export interface MapModel {
  kind: "map";
  points: { name: string; lat: number; lon: number; value: number | null }[];
}

export interface FilledMapModel {
  kind: "filledMap";
  regions: { name: string; value: number }[];
}

export interface NoteModel {
  kind: "note";
  message: string;
}

export type RenderModel =
  | CartesianModel | PieModel | CardModel | TableModel
  | ScatterModel | FunnelModel | GaugeModel | TreemapModel | WaterfallModel
  | MapModel | FilledMapModel | NoteModel;

export function renderModel(type: string, dsr: DSR | null, extraTooltipCount = 0, options: { lineCount?: number } = {}): RenderModel {
  const spec = visualSpec(type);
  if (spec.renders === "none" || spec.renders === "slicer") {
    return { kind: "note", message: "This visual is not drawn as a chart." };
  }
  if (!dsr) {
    return { kind: "note", message: "Add fields to run a query." };
  }
  if (dsr.rows.length === 0) {
    return { kind: "note", message: "Nothing recorded for this view yet" };
  }
  if (spec.renders === "card") return { kind: "card", value: text(firstMeasure(dsr)), format: firstFormat(dsr) };
  if (spec.renders === "table") {
    return {
      kind: "table",
      columns: dsr.columns.map((column) => column.name),
      rows: dsr.rows.map((row) => row.map((cell) => text(cell))),
    };
  }
  if (spec.renders === "map") return mapModel(dsr);
  if (spec.renders === "filledMap") return { kind: "filledMap", regions: pie(dsr).slices };
  if (spec.renders === "pie") return pie(dsr);
  if (spec.renders === "scatter") return scatter(dsr);
  if (spec.renders === "funnel") return funnelModel(dsr);
  if (spec.renders === "gauge") return gaugeModel(dsr);
  if (spec.renders === "treemap") return treemapModel(dsr);
  if (spec.renders === "waterfall") return waterfallModel(dsr);
  const model = cartesian(dsr, spec.orientation ?? "column", extraTooltipCount);
  return {
    ...model,
    ...(spec.stack ? { stack: spec.stack } : {}),
    ...(spec.area ? { area: true } : {}),
    ...(options.lineCount ? { lineCount: options.lineCount } : {}),
  };
}

/** Each category's values as shares of that category's total, in percent. */
export function percentOfCategory(series: { name: string; values: number[] }[]): { name: string; values: number[] }[] {
  const totals = series[0]?.values.map((_, index) => series.reduce((sum, item) => sum + Math.abs(item.values[index] ?? 0), 0)) ?? [];
  return series.map((item) => ({
    name: item.name,
    values: item.values.map((value, index) => (totals[index] ? (100 * value) / totals[index] : 0)),
  }));
}

function cartesian(dsr: DSR, orientation: "column" | "bar" | "line", extraTooltipCount = 0): CartesianModel {
  const chart = extraTooltipCount > 0
    ? {
        ...dsr,
        columns: dsr.columns.slice(0, -extraTooltipCount),
        rows: dsr.rows.map((row) => row.slice(0, -extraTooltipCount)),
      }
    : dsr;
  const measures = indexes(chart, true);
  const groups = indexes(chart, false);
  const categoryIndex = groups[0];
  const legendIndex = groups[1];
  const extras = extraTooltipCount > 0 ? dsr.columns.slice(-extraTooltipCount) : [];
  const extraStart = dsr.columns.length - extraTooltipCount;
  function tooltipValues(categories: string[]): { name: string; values: string[] }[] {
    return extras.map((column, offset) => ({
      name: column.name,
      values: categories.map((category, rowIndex) => {
        const row = categoryIndex === undefined
          ? dsr.rows[rowIndex]
          : dsr.rows.find((item) => text(item[categoryIndex]) === category);
        return row ? text(row[extraStart + offset]) : "";
      }),
    }));
  }
  if (categoryIndex === undefined) {
    const categories = chart.rows.map((_, index) => String(index + 1));
    return {
      kind: "cartesian",
      orientation,
      categories,
      series: seriesFrom(chart, measures),
      tooltips: tooltipValues(categories),
    };
  }
  if (legendIndex === undefined) {
    const ordered = orderMonths(
      chart.rows.map((row) => text(row[categoryIndex])),
      seriesFrom(chart, measures),
    );
    return { kind: "cartesian", orientation, ...ordered, tooltips: tooltipValues(ordered.categories) };
  }
  const categories = unique(chart.rows.map((row) => text(row[categoryIndex])));
  const legends = unique(chart.rows.map((row) => text(row[legendIndex])));
  const measure = measures[0];
  return {
    kind: "cartesian",
    orientation,
    categories,
    series: legends.map((legend) => ({
      name: legend,
      values: categories.map((category) => {
        const row = chart.rows.find(
          (item) => text(item[categoryIndex]) === category && text(item[legendIndex]) === legend,
        );
        return row && measure !== undefined ? number(row[measure]) : 0;
      }),
    })),
    tooltips: tooltipValues(categories),
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

/** Points from [Location], Latitude, Longitude and an optional size measure, in that order. */
function mapModel(dsr: DSR): MapModel | NoteModel {
  const groups = indexes(dsr, false);
  const measure = indexes(dsr, true)[0];
  if (groups.length < 2) return { kind: "note", message: "Add latitude and longitude to place points." };
  const [nameAt, latAt, lonAt] = groups.length >= 3 ? groups : [undefined, groups[0], groups[1]];
  const points = dsr.rows
    .map((row, index) => ({
      name: nameAt === undefined ? String(index + 1) : text(row[nameAt]),
      lat: Number(row[latAt!]),
      lon: Number(row[lonAt!]),
      value: measure === undefined ? null : number(row[measure]),
    }))
    .filter((point) => Number.isFinite(point.lat) && Number.isFinite(point.lon) && Math.abs(point.lat) <= 90 && Math.abs(point.lon) <= 180);
  if (points.length === 0) return { kind: "note", message: "None of the rows has a usable latitude and longitude." };
  return { kind: "map", points };
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

function orderMonths(
  categories: string[],
  series: { name: string; values: number[] }[],
): { categories: string[]; series: { name: string; values: number[] }[] } {
  return arrangeMonths(categories, series) ?? { categories, series };
}

function seriesFrom(dsr: DSR, measures: number[]): { name: string; values: number[] }[] {
  return measures.map((index) => ({
    name: dsr.columns[index]?.name ?? "Value",
    values: dsr.rows.map((row) => number(row[index])),
  }));
}

function firstFormat(dsr: DSR): string | null {
  return dsr.columns.find((column) => column.isMeasure)?.format ?? null;
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
