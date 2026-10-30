import { useDesignerStore } from "./store";
import { visualSpec } from "./catalog";

export function SelectionPane({ onClose }: { onClose: () => void }) {
  const report = useDesignerStore((s) => s.report);
  const activePageIndex = useDesignerStore((s) => s.activePageIndex);
  const selectedId = useDesignerStore((s) => s.selectedVisualId);
  const selectVisual = useDesignerStore((s) => s.selectVisual);
  const setProperties = useDesignerStore((s) => s.setProperties);
  const page = report.pages[activePageIndex];
  const visuals = page?.visuals ?? [];

  return (
    <div className="selection-pane">
      <div className="sp-header">
        <span className="sp-title">Selection</span>
        <button type="button" className="sp-close" onClick={onClose}>×</button>
      </div>
      {visuals.length === 0 && <p className="hint">No visuals on this page.</p>}
      {visuals.map((visual, index) => {
        const spec = visualSpec(visual.type);
        const title = typeof visual.properties?.title === "string" && visual.properties.title
          ? visual.properties.title
          : `${spec.displayName} ${index + 1}`;
        const hidden = Boolean(visual.properties?.hidden);
        return (
          <button
            key={visual.id}
            type="button"
            className={`sp-item${visual.id === selectedId ? " active" : ""}`}
            onClick={() => selectVisual(visual.id)}
          >
            <span className="sp-type">{spec.abbr}</span>
            <span className="sp-name">{title}</span>
            <span
              className="sp-hidden"
              onClick={(event) => {
                event.stopPropagation();
                setProperties(visual.id, { hidden: !hidden });
              }}
            >
              {hidden ? "Show" : "Hide"}
            </span>
          </button>
        );
      })}
    </div>
  );
}
