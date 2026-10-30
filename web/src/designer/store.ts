import { create } from "zustand";

import type { FieldBinding, FilterDefinition, ReportDefinition, VisualDefinition } from "../types/report";
import { patchFormat } from "./filters";
import { EMPTY_HISTORY, record, redo, undo, type History } from "./history";
import { blankReport, PAGE_HEIGHT, PAGE_WIDTH, placeVisual, type Box } from "./layout";

interface DesignerState {
  report: ReportDefinition;
  history: History;
  activePageIndex: number;
  selectedVisualId: string | null;
  clipboard: VisualDefinition | null;
  selectVisual: (id: string | null) => void;
  replaceReport: (report: ReportDefinition) => void;
  addVisual: (type: string) => void;
  moveVisual: (id: string, x: number, y: number) => void;
  resizeVisual: (id: string, box: Box) => void;
  removeVisual: (id: string) => void;
  removeAllVisuals: () => void;
  saveStatus: "saved" | "saving" | "dirty";
  setSaveStatus: (status: "saved" | "saving" | "dirty") => void;
  setWells: (id: string, wells: Record<string, FieldBinding[]>) => void;
  setPageFilters: (filters: FilterDefinition[]) => void;
  setReportFilters: (filters: FilterDefinition[]) => void;
  setVisualFilters: (id: string, filters: FilterDefinition[]) => void;
  setInteraction: (id: string, targetId: string, mode: "crossFilter" | "crossHighlight" | "none") => void;
  setFormat: (id: string, title: string, color: string) => void;
  setProperties: (id: string, props: Record<string, unknown>) => void;
  setTheme: (colors: string[]) => void;
  switchPage: (index: number) => void;
  addPage: () => void;
  removePage: (index: number) => void;
  copyVisual: (id: string) => void;
  pasteVisual: () => void;
  bringToFront: (id: string) => void;
  sendToBack: (id: string) => void;
  drillThrough: (pageIndex: number, filters: FilterDefinition[]) => void;
  undo: () => void;
  redo: () => void;
}

export const useDesignerStore = create<DesignerState>((set, get) => ({
  report: blankReport("Report", ""),
  history: EMPTY_HISTORY,
  activePageIndex: 0,
  selectedVisualId: null,
  saveStatus: "saved",
  setSaveStatus: (status) => set({ saveStatus: status }),
  clipboard: null,
  selectVisual: (id) => set({ selectedVisualId: id }),
  replaceReport: (report) => set({ report, history: EMPTY_HISTORY, selectedVisualId: null, activePageIndex: 0 }),

  switchPage: (index) => {
    const pages = get().report.pages;
    if (index >= 0 && index < pages.length) {
      set({ activePageIndex: index, selectedVisualId: null });
    }
  },

  addPage: () => {
    const report = get().report;
    const num = report.pages.length + 1;
    const newPage = {
      name: `page-${num}`,
      displayName: `Page ${num}`,
      width: PAGE_WIDTH,
      height: PAGE_HEIGHT,
      visuals: [] as VisualDefinition[],
      filters: [] as FilterDefinition[],
    };
    const next = { ...report, pages: [...report.pages, newPage] };
    commit(set, get, next);
    set({ activePageIndex: report.pages.length, selectedVisualId: null });
  },

  removePage: (index) => {
    const report = get().report;
    if (report.pages.length <= 1) return;
    const pages = report.pages.filter((_, i) => i !== index);
    const next = { ...report, pages };
    commit(set, get, next);
    const current = get().activePageIndex;
    if (current >= pages.length) {
      set({ activePageIndex: pages.length - 1, selectedVisualId: null });
    } else if (current === index) {
      set({ selectedVisualId: null });
    }
  },

  addVisual: (type) => {
    const report = get().report;
    const pageIndex = get().activePageIndex;
    const page = report.pages[pageIndex];
    if (!page) return;
    const visual = placeVisual(page.visuals, type, crypto.randomUUID());
    commit(set, get, {
      ...report,
      pages: report.pages.map((p, i) =>
        i === pageIndex ? { ...p, visuals: [...p.visuals, visual] } : p,
      ),
    });
    set({ selectedVisualId: visual.id });
  },

  moveVisual: (id, x, y) => {
    const report = get().report;
    const pageIndex = get().activePageIndex;
    const page = report.pages[pageIndex];
    if (!page) return;
    const visuals = page.visuals.map((v) => (v.id === id ? moved(v, x, y) : v));
    commit(set, get, {
      ...report,
      pages: report.pages.map((p, i) => (i === pageIndex ? { ...p, visuals } : p)),
    });
  },

  resizeVisual: (id, box) => {
    updateVisual(set, get, id, (v) => ({ ...v, ...box }));
  },

  removeVisual: (id) => {
    const report = get().report;
    const pageIndex = get().activePageIndex;
    const page = report.pages[pageIndex];
    if (!page) return;
    commit(set, get, {
      ...report,
      pages: report.pages.map((p, i) =>
        i === pageIndex ? { ...p, visuals: p.visuals.filter((v) => v.id !== id) } : p,
      ),
    });
    if (get().selectedVisualId === id) set({ selectedVisualId: null });
  },
  removeAllVisuals: () => {
    const report = get().report;
    const pageIndex = get().activePageIndex;
    const page = report.pages[pageIndex];
    if (!page || page.visuals.length === 0) return;
    commit(set, get, {
      ...report,
      pages: report.pages.map((item, index) => (index === pageIndex ? { ...item, visuals: [] } : item)),
    });
    set({ selectedVisualId: null });
  },

  setWells: (id, wells) => {
    updateVisual(set, get, id, (v) => ({ ...v, wells }));
  },

  setReportFilters: (filters) => {
    commit(set, get, { ...get().report, filters });
  },
  setVisualFilters: (id, filters) => {
    updateVisual(set, get, id, (visual) => ({ ...visual, filters }));
  },
  setInteraction: (id, targetId, mode) => {
    updateVisual(set, get, id, (visual) => ({
      ...visual,
      interactions: {
        source: visual.id,
        targets: { ...visual.interactions?.targets, [targetId]: mode },
      },
    }));
  },
  setPageFilters: (filters) => {
    const report = get().report;
    const pageIndex = get().activePageIndex;
    const page = report.pages[pageIndex];
    if (!page) return;
    commit(set, get, {
      ...report,
      pages: report.pages.map((p, i) => (i === pageIndex ? { ...p, filters } : p)),
    });
  },

  setFormat: (id, title, color) => {
    updateVisual(set, get, id, (v) => patchFormat(v, title, color));
  },

  setProperties: (id, props) => {
    updateVisual(set, get, id, (v) => ({
      ...v,
      properties: { ...v.properties, ...props },
    }));
  },

  setTheme: (colors) => {
    const report = get().report;
    commit(set, get, { ...report, theme: { ...report.theme, colors } });
  },

  copyVisual: (id) => {
    const page = get().report.pages[get().activePageIndex];
    const visual = page?.visuals.find((v) => v.id === id);
    if (visual) set({ clipboard: { ...visual } });
  },

  pasteVisual: () => {
    const { clipboard, report, activePageIndex } = get();
    if (!clipboard) return;
    const page = report.pages[activePageIndex];
    if (!page) return;
    const newVisual: VisualDefinition = {
      ...clipboard,
      id: crypto.randomUUID(),
      x: Math.min(clipboard.x + 40, PAGE_WIDTH - clipboard.width),
      y: Math.min(clipboard.y + 40, PAGE_HEIGHT - clipboard.height),
    };
    commit(set, get, {
      ...report,
      pages: report.pages.map((p, i) =>
        i === activePageIndex ? { ...p, visuals: [...p.visuals, newVisual] } : p,
      ),
    });
    set({ selectedVisualId: newVisual.id });
  },

  bringToFront: (id) => {
    const report = get().report;
    const pageIndex = get().activePageIndex;
    const page = report.pages[pageIndex];
    if (!page) return;
    const visual = page.visuals.find((v) => v.id === id);
    if (!visual) return;
    const others = page.visuals.filter((v) => v.id !== id);
    commit(set, get, {
      ...report,
      pages: report.pages.map((p, i) =>
        i === pageIndex ? { ...p, visuals: [...others, visual] } : p,
      ),
    });
  },

  sendToBack: (id) => {
    const report = get().report;
    const pageIndex = get().activePageIndex;
    const page = report.pages[pageIndex];
    if (!page) return;
    const visual = page.visuals.find((v) => v.id === id);
    if (!visual) return;
    const others = page.visuals.filter((v) => v.id !== id);
    commit(set, get, {
      ...report,
      pages: report.pages.map((p, i) =>
        i === pageIndex ? { ...p, visuals: [visual, ...others] } : p,
      ),
    });
  },

  drillThrough: (pageIndex, filters) => {
    const report = get().report;
    const page = report.pages[pageIndex];
    if (!page) return;
    commit(set, get, {
      ...report,
      pages: report.pages.map((p, i) =>
        i === pageIndex ? { ...p, filters: [...(p.filters ?? []), ...filters] } : p,
      ),
    });
    set({ activePageIndex: pageIndex, selectedVisualId: null });
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
  map: (v: VisualDefinition) => VisualDefinition,
) {
  const report = get().report;
  const pageIndex = get().activePageIndex;
  const page = report.pages[pageIndex];
  if (!page) return;
  const visuals = page.visuals.map((v) => (v.id === id ? map(v) : v));
  commit(set, get, {
    ...report,
    pages: report.pages.map((p, i) => (i === pageIndex ? { ...p, visuals } : p)),
  });
}

function moved(visual: VisualDefinition, x: number, y: number): VisualDefinition {
  return {
    ...visual,
    x: Math.min(Math.max(x, 0), Math.max(PAGE_WIDTH - visual.width, 0)),
    y: Math.min(Math.max(y, 0), Math.max(PAGE_HEIGHT - visual.height, 0)),
  };
}
