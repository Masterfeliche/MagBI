/**
 * Report document for the designer. Undo patches are recorded on commit, not on pointer move.
 */
import { create } from "zustand";

import type { FieldBinding, FilterDefinition, ReportDefinition, VisualDefinition } from "../types/report";
import { patchFormat } from "./filters";
import { EMPTY_HISTORY, record, redo, undo, type History } from "./history";
import { blankReport, PAGE_HEIGHT, PAGE_WIDTH, placeVisual, type Box } from "./layout";

interface DesignerState {
  report: ReportDefinition;
  history: History;
  selectedVisualId: string | null;
  selectVisual: (id: string | null) => void;
  replaceReport: (report: ReportDefinition) => void;
  addVisual: (type: string) => void;
  moveVisual: (id: string, x: number, y: number) => void;
  resizeVisual: (id: string, box: Box) => void;
  setWells: (id: string, wells: Record<string, FieldBinding[]>) => void;
  setPageFilters: (filters: FilterDefinition[]) => void;
  setFormat: (id: string, title: string, color: string) => void;
  undo: () => void;
  redo: () => void;
}

export const useDesignerStore = create<DesignerState>((set, get) => ({
  report: blankReport("Report", ""),
  history: EMPTY_HISTORY,
  selectedVisualId: null,
  selectVisual: (id) => set({ selectedVisualId: id }),
  replaceReport: (report) => set({ report, history: EMPTY_HISTORY, selectedVisualId: null }),
  addVisual: (type) => {
    const report = get().report;
    const page = report.pages[0];
    if (!page) return;
    const visual = placeVisual(page.visuals, type, crypto.randomUUID());
    commit(set, get, {
      ...report,
      pages: [{ ...page, visuals: [...page.visuals, visual] }],
    });
    set({ selectedVisualId: visual.id });
  },
  moveVisual: (id, x, y) => {
    const report = get().report;
    const page = report.pages[0];
    if (!page) return;
    const visuals = page.visuals.map((visual) =>
      visual.id === id ? moved(visual, x, y) : visual,
    );
    commit(set, get, { ...report, pages: [{ ...page, visuals }] });
  },
  resizeVisual: (id, box) => {
    updateVisual(set, get, id, (visual) => ({ ...visual, ...box }));
  },
  setWells: (id, wells) => {
    updateVisual(set, get, id, (visual) => ({ ...visual, wells }));
  },
  setPageFilters: (filters) => {
    const report = get().report;
    const page = report.pages[0];
    if (!page) return;
    commit(set, get, { ...report, pages: [{ ...page, filters }] });
  },
  setFormat: (id, title, color) => {
    updateVisual(set, get, id, (visual) => patchFormat(visual, title, color));
  },
  undo: () => {
    const result = undo(get().report, get().history);
    set({ report: result.doc, history: result.history });
  },
  redo: () => {
    const result = redo(get().report, get().history);
    set({ report: result.doc, history: result.history });
  },
}));

function commit(
  set: (partial: Partial<DesignerState>) => void,
  get: () => DesignerState,
  next: ReportDefinition,
) {
  set({ report: next, history: record(get().report, next, get().history) });
}

function updateVisual(
  set: (partial: Partial<DesignerState>) => void,
  get: () => DesignerState,
  id: string,
  map: (visual: VisualDefinition) => VisualDefinition,
) {
  const report = get().report;
  const page = report.pages[0];
  if (!page) return;
  const visuals = page.visuals.map((visual) => (visual.id === id ? map(visual) : visual));
  commit(set, get, { ...report, pages: [{ ...page, visuals }] });
}

function moved(visual: VisualDefinition, x: number, y: number): VisualDefinition {
  return {
    ...visual,
    x: Math.min(Math.max(x, 0), Math.max(PAGE_WIDTH - visual.width, 0)),
    y: Math.min(Math.max(y, 0), Math.max(PAGE_HEIGHT - visual.height, 0)),
  };
}
