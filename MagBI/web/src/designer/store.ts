/**
 * Zustand store for report designer state.
 * Undo/redo via JSON Patch (RFC 6902).
 */
import { create } from "zustand";

interface DesignerState {
  selectedVisualId: string | null;
  selectVisual: (id: string | null) => void;
}

export const useDesignerStore = create<DesignerState>((set) => ({
  selectedVisualId: null,
  selectVisual: (id) => set({ selectedVisualId: id }),
}));
