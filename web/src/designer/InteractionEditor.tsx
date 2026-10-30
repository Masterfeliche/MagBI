/** Choose how the selected visual filters each other visual. */

import { useDesignerStore } from "./store";

const MODES = ["crossFilter", "crossHighlight", "none"] as const;

export function InteractionEditor() {
  const selectedId = useDesignerStore((s) => s.selectedVisualId);
  const report = useDesignerStore((s) => s.report);
  const pageIndex = useDesignerStore((s) => s.activePageIndex);
  const setInteraction = useDesignerStore((s) => s.setInteraction);
  const page = report.pages[pageIndex];
  const selected = page?.visuals.find((visual) => visual.id === selectedId);
  if (!selected || !page) return <p className="hint">Select a visual to edit interactions.</p>;
  const others = page.visuals.filter((visual) => visual.id !== selected.id);

  return (
    <div className="interaction-editor">
      {others.length === 0 && <p className="hint">Add another visual to set interactions.</p>}
      {others.map((visual) => {
        const mode = selected.interactions?.targets[visual.id] ?? "crossFilter";
        return (
          <label key={visual.id} className="slicer-row">
            {visual.properties?.title ? String(visual.properties.title) : visual.type}
            <select
              value={mode}
              onChange={(event) => setInteraction(selected.id, visual.id, event.target.value as (typeof MODES)[number])}
            >
              {MODES.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </label>
        );
      })}
    </div>
  );
}
