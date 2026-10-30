import { useDesignerStore } from "./store";

const TYPES = [
  { id: "rules", label: "Status rules" },
  { id: "colorScale", label: "Color scale" },
  { id: "dataBar", label: "Data bars" },
  { id: "cardSign", label: "Card sign" },
] as const;

export function ConditionalFormatDialog({ onClose }: { onClose: () => void }) {
  const selectedId = useDesignerStore((state) => state.selectedVisualId);
  const setProperties = useDesignerStore((state) => state.setProperties);
  if (!selectedId) return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <p>Select a visual first.</p>
        <button type="button" className="ws-btn" onClick={onClose}>Close</button>
      </div>
    </div>
  );
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <h3>Conditional format</h3>
        {TYPES.map((item) => (
          <button
            key={item.id}
            type="button"
            className="ws-btn"
            onClick={() => {
              setProperties(selectedId, { condFormat: item.id });
              onClose();
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}
