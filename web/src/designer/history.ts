/** JSON-patch undo. A drag records one patch when the pointer goes up. */

import { applyPatch, compare, type Operation } from "fast-json-patch";

import type { ReportDefinition } from "../types/report";

export interface HistoryStep {
  undo: Operation[];
  redo: Operation[];
}

export interface History {
  past: HistoryStep[];
  future: HistoryStep[];
}

export const EMPTY_HISTORY: History = { past: [], future: [] };

export function record(before: ReportDefinition, after: ReportDefinition, history: History): History {
  const redo = compare(before, after) as Operation[];
  if (redo.length === 0) return history;
  const undo = compare(after, before) as Operation[];
  return { past: [...history.past, { undo, redo }], future: [] };
}

export function undo(doc: ReportDefinition, history: History): { doc: ReportDefinition; history: History } {
  const step = history.past[history.past.length - 1];
  if (!step) return { doc, history };
  return {
    doc: apply(doc, step.undo),
    history: { past: history.past.slice(0, -1), future: [...history.future, step] },
  };
}

export function redo(doc: ReportDefinition, history: History): { doc: ReportDefinition; history: History } {
  const step = history.future[history.future.length - 1];
  if (!step) return { doc, history };
  return {
    doc: apply(doc, step.redo),
    history: { past: [...history.past, step], future: history.future.slice(0, -1) },
  };
}

function apply(doc: ReportDefinition, patch: Operation[]): ReportDefinition {
  const copy = structuredClone(doc);
  const result = applyPatch(copy, patch, true, false);
  return result.newDocument as ReportDefinition;
}
