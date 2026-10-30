import { useState } from "react";

import type { FilterDefinition } from "../types/report";
import type { DesignerTable } from "./model";
import { useDesignerStore } from "./store";
import { pageFilter, type FilterOperator } from "./filters";

type FilterLevel = "visual" | "page" | "report";

export function FilterPane({
  tables,
  filters,
  onChange,
}: {
  tables: DesignerTable[];
  filters: FilterDefinition[];
  onChange: (filters: FilterDefinition[]) => void;
}) {
  const selectedId = useDesignerStore((s) => s.selectedVisualId);
  const report = useDesignerStore((s) => s.report);
  const activePageIndex = useDesignerStore((s) => s.activePageIndex);
  const page = report.pages[activePageIndex];
  const selected = page?.visuals.find((v) => v.id === selectedId);

  const [level, setLevel] = useState<FilterLevel>("page");
  const columns = tables.flatMap((table) =>
    table.fields
      .filter((f) => f.kind === "column")
      .map((f) => ({ table: table.name, column: f.name })),
  );
  const [choice, setChoice] = useState(columns[0] ? `${columns[0].table}.${columns[0].column}` : "");
  const setReportFilters = useDesignerStore((s) => s.setReportFilters);
  const setVisualFilters = useDesignerStore((s) => s.setVisualFilters);
  const [operator, setOperator] = useState<FilterOperator>("eq");
  const [raw, setRaw] = useState("");

  const visualFilters = selected?.filters ?? [];
  const pageFilters = filters;
  const reportFilters = report.filters ?? [];

  const activeFilters = level === "visual" ? visualFilters : level === "page" ? pageFilters : reportFilters;

  function addFilter() {
    const [table, column] = choice.split(".");
    if (!table || !column || raw.trim() === "") return;
    const newFilter = pageFilter(table, column, operator, raw.trim());
    if (level === "page") onChange([...pageFilters, newFilter]);
    if (level === "report") setReportFilters([...reportFilters, newFilter]);
    if (level === "visual" && selected) setVisualFilters(selected.id, [...visualFilters, newFilter]);
    setRaw("");
  }

  function removeFilter(index: number) {
    if (level === "page") onChange(pageFilters.filter((_, i) => i !== index));
    if (level === "report") setReportFilters(reportFilters.filter((_, i) => i !== index));
    if (level === "visual" && selected) {
      setVisualFilters(selected.id, visualFilters.filter((_, i) => i !== index));
    }
  }

  return (
    <div className="filter-section">
      <div className="filter-levels">
        {(["visual", "page", "report"] as const).map((l) => (
          <button
            key={l}
            type="button"
            className={`filter-level${level === l ? " active" : ""}`}
            onClick={() => setLevel(l)}
          >
            {l.charAt(0).toUpperCase() + l.slice(1)}
            {l === "visual" && !selectedId && " —"}
          </button>
        ))}
      </div>

      {level === "visual" && !selectedId ? (
        <p className="hint">Select a visual to see its filters.</p>
      ) : (
        <>
          {activeFilters.length === 0 && <p className="hint">No {level} filters.</p>}
          {activeFilters.map((filter, index) => (
            <div key={`${filter.table}.${filter.column}.${index}`} className="filter-card">
              <div className="fc-header">
                <span className="fc-field">{filter.table}.{filter.column}</span>
                <button type="button" className="fc-remove" onClick={() => removeFilter(index)}>×</button>
              </div>
              <div className="fc-value">
                {Array.isArray((filter.config as { values?: unknown[] })?.values)
                  ? ((filter.config as { values: string[] }).values).join(", ")
                  : "configured"}
              </div>
            </div>
          ))}

          <div className="filter-add">
            <select className="fmt-select" value={choice} onChange={(e) => setChoice(e.target.value)}>
              {columns.map((c) => {
                const key = `${c.table}.${c.column}`;
                return <option key={key} value={key}>{key}</option>;
              })}
            </select>
            <select className="fmt-select" value={operator} onChange={(e) => setOperator(e.target.value as FilterOperator)}>
              <option value="eq">is</option>
              <option value="ne">is not</option>
              <option value="gt">greater than</option>
              <option value="gte">at least</option>
              <option value="lt">less than</option>
              <option value="lte">at most</option>
              <option value="in">is any of</option>
              <option value="contains">contains</option>
              <option value="startsWith">starts with</option>
            </select>
            <input className="fmt-input" placeholder="Value" value={raw} onChange={(e) => setRaw(e.target.value)} />
            <button type="button" className="filter-add-btn" onClick={addFilter}>+ Add filter</button>
          </div>
        </>
      )}
    </div>
  );
}
