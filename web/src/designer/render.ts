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

export interface NoteModel {
  kind: "note";
  message: string;
}

export type RenderModel = CartesianModel | PieModel | CardModel | TableModel | NoteModel;

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
