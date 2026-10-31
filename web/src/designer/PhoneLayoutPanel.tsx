/** Desktop / Phone tabs above the canvas, and the phone layout's list of visuals not placed yet. */

import { visualSpec } from "./catalog";
import { hasPhoneLayout, unplacedVisuals } from "./phone";
import { useDesignerStore } from "./store";

export function LayoutTabs() {
  const mode = useDesignerStore((s) => s.layoutMode);
  const setMode = useDesignerStore((s) => s.setLayoutMode);
  const selectVisual = useDesignerStore((s) => s.selectVisual);
  return (
    <div className="layout-tabs" role="tablist" aria-label="Layout">
      {(["desktop", "phone"] as const).map((item) => (
        <button
          key={item}
          type="button"
          role="tab"
          aria-selected={mode === item}
          className={`layout-tab${mode === item ? " active" : ""}`}
          onClick={() => {
            setMode(item);
            selectVisual(null);
          }}
        >
          {item === "desktop" ? "🖥 Desktop" : "📱 Phone"}
        </button>
      ))}
    </div>
  );
}

export function PhoneLayoutPanel() {
  const report = useDesignerStore((s) => s.report);
  const activePageIndex = useDesignerStore((s) => s.activePageIndex);
  const selectedId = useDesignerStore((s) => s.selectedVisualId);
  const addToPhone = useDesignerStore((s) => s.addToPhone);
  const removeFromPhone = useDesignerStore((s) => s.removeFromPhone);
  const autoArrange = useDesignerStore((s) => s.autoArrangePhone);
  const clearLayout = useDesignerStore((s) => s.clearPhoneLayout);
  const page = report.pages[activePageIndex];
  const unplaced = unplacedVisuals(page);
  const placed = hasPhoneLayout(page);
  const selectedPlaced = Boolean(selectedId && page?.phone?.visuals.some((item) => item.id === selectedId));

  return (
    <aside className="phone-panel" aria-label="Phone layout">
      <h3>Phone layout</h3>
      <p className="hint">
        {placed
          ? "Phones and windows under 768 px show this page as arranged here. Visuals left off aren't shown on a phone."
          : "No phone layout yet: phones show the desktop page shrunk to fit. Add visuals, or start from Auto arrange."}
      </p>
      <div className="phone-actions">
        <button type="button" className="ws-btn small" onClick={autoArrange} title="Replace this page's phone layout with the desktop visuals stacked in reading order">
          Auto arrange
        </button>
        {placed && (
          <button type="button" className="ws-btn small" onClick={clearLayout} title="Phones show the desktop page again">
            Clear
          </button>
        )}
        {selectedPlaced && selectedId && (
          <button type="button" className="ws-btn small" onClick={() => removeFromPhone(selectedId)}>
            Remove selected
          </button>
        )}
      </div>
      <h4>Not on the phone ({unplaced.length})</h4>
      {unplaced.length === 0 && <p className="hint">Every visual on this page is placed.</p>}
      <ul className="phone-unplaced">
        {unplaced.map((visual) => {
          const spec = visualSpec(visual.type);
          // Standard-kit types (header, kpi, chain…) aren't in the gallery's list.
          const known = spec.type === visual.type;
          const title = visualTitle(visual.properties) || (known ? spec.displayName : visual.type);
          return (
            <li key={visual.id}>
              <span className="sp-type">{known ? spec.abbr : visual.type.slice(0, 3).toUpperCase()}</span>
              <span className="phone-name" title={title}>{title}</span>
              <button type="button" className="ws-btn small" onClick={() => addToPhone(visual.id)} aria-label={`Add ${title} to the phone layout`}>
                Add
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

function visualTitle(properties: Record<string, unknown> | undefined): string {
  for (const key of ["title", "caption", "text"]) {
    const value = properties?.[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}
