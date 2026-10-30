import type { VisualDefinition } from "../types/report";
import { visualSpec } from "./catalog";

export function TooltipPreview({ visual, x, y }: { visual: VisualDefinition; x: number; y: number }) {
  const spec = visualSpec(visual.type);
  const wells = Object.entries(visual.wells).filter(([, bindings]) => bindings.length > 0);
  return (
    <div className="tooltip-preview" style={{ left: x + 12, top: y + 12 }}>
      <div className="tp-type">{spec.displayName}</div>
      {wells.map(([name, bindings]) => (
        <div key={name} className="tp-well">
          <span className="tp-well-name">{name}:</span>
          {bindings.map((b, i) => (
            <span key={i} className="tp-field">{b.column || b.measure || b.table}</span>
          ))}
        </div>
      ))}
      {wells.length === 0 && <div className="tp-empty">No fields bound</div>}
    </div>
  );
}
