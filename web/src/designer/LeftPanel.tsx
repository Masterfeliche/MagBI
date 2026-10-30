import { VISUALS } from "./catalog";
import { useDesignerStore } from "./store";
import type { FilterDefinition } from "../types/report";
import type { DesignerTable } from "./model";
import { FilterPane } from "./FilterPane";

export function LeftPanel({
  tables,
  filters,
  onFiltersChange,
}: {
  tables: DesignerTable[];
  filters: FilterDefinition[];
  onFiltersChange: (filters: FilterDefinition[]) => void;
}) {
  const addVisual = useDesignerStore((s) => s.addVisual);

  return (
    <div className="left-panel">
      <div className="panel-header">Visualizations</div>
      <div className="viz-gallery">
        <div className="viz-grid">
          {VISUALS.map((item) => (
            <button
              key={item.type}
              type="button"
              className="viz-item"
              title={item.displayName}
              onClick={() => addVisual(item.type)}
            >
              {item.icon ? (
                <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                  <path d={item.icon} fill="currentColor" />
                </svg>
              ) : (
                item.abbr
              )}
            </button>
          ))}
        </div>
      </div>
      <div className="panel-header">Filters</div>
      <FilterPane tables={tables} filters={filters} onChange={onFiltersChange} />
    </div>
  );
}
