/**
 * Report document for the designer. Undo patches are recorded on commit, not on pointer move.
 */
import { create } from "zustand";

import type { FieldBinding, FilterDefinition, ReportDefinition, VisualDefinition } from "../types/report";
import { patchFormat } from "./filters";
import { blankReport, clampPosition, placeVisual } from "./layout";

interface DesignerState {
  report: ReportDefinition;
  selectedVisualId: string | null;
  selectVisual: (id: string | null) => void;
  replaceReport: (report: ReportDefinition) => void;
  addVisual: (type: string) => void;
  moveVisual: (id: string, x: number, y: number) => void;
  setWells: (id: string, wells: Record<string, FieldBinding[]>) => void;
  setPageFilters: (filters: FilterDefinition[]) => void;
  setFormat: (id: string, title: string, color: string) => void;
}

export const useDesignerStore = create<DesignerState>((set, get) => ({
  report: blankReport("Report", ""),
  selectedVisualId: null,
  selectVisual: (id) => set({ selectedVisualId: id }),
  replaceReport: (report) => set({ report }),
  addVisual: (type) => {
    const report = get().report;
    const page = report.pages[0];
    if (!page) return;
    const visual = placeVisual(page.visuals, type, crypto.randomUUID());
    set({
      report: { ...report, pages: [{ ...page, visuals: [...page.visuals, visual] }] },
      selectedVisualId: visual.id,
    });
  },
  moveVisual: (id, x, y) => {
    const report = get().report;
    const page = report.pages[0];
    if (!page) return;
    const visuals = page.visuals.map((visual) =>
      visual.id === id ? moved(visual, x, y) : visual,
    );
    set({ report: { ...report, pages: [{ ...page, visuals }] } });
  },
  setWells: (id, wells) => {
    const report = get().report;
    const page = report.pages[0];
    if (!page) return;
    const visuals = page.visuals.map((visual) => (visual.id === id ? { ...visual, wells } : visual));
    set({ report: { ...report, pages: [{ ...page, visuals }] } });
  },
  setPageFilters: (filters) => {
    const report = get().report;
    const page = report.pages[0];
    if (!page) return;
    set({ report: { ...report, pages: [{ ...page, filters }] } });
  },
  setFormat: (id, title, color) => {
    const report = get().report;
    const page = report.pages[0];
    if (!page) return;
    const visuals = page.visuals.map((visual) =>
      visual.id === id ? patchFormat(visual, title, color) : visual,
    );
    set({ report: { ...report, pages: [{ ...page, visuals }] } });
  },
}));

function moved(visual: VisualDefinition, x: number, y: number): VisualDefinition {
  return { ...visual, ...clampPosition(x, y, visual.width, visual.height) };
}
