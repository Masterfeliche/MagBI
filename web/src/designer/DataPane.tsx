import { useState } from "react";
import { useDraggable } from "@dnd-kit/core";

import type { DesignerField, DesignerTable } from "./model";

export function DataPane({ tables }: { tables: DesignerTable[] }) {
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const query = search.toLowerCase();

  const filtered = tables
    .map((table) => ({
      ...table,
      fields: query
        ? table.fields.filter((f) => f.name.toLowerCase().includes(query) || table.name.toLowerCase().includes(query))
        : table.fields,
    }))
    .filter((t) => t.fields.length > 0);

  return (
    <div className="data-pane">
      <div className="dp-search">
        <input
          className="fmt-input"
          placeholder="Search fields..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      {filtered.map((table) => {
        const isOpen = !collapsed[table.name];
        return (
          <div key={table.name} className="dp-table">
            <button
              type="button"
              className="dp-table-header"
              onClick={() => setCollapsed((s) => ({ ...s, [table.name]: !s[table.name] }))}
            >
              <span className="dp-chevron">{isOpen ? "▾" : "▸"}</span>
              <span className="dp-table-icon">⊞</span>
              {table.name}
            </button>
            {isOpen && table.fields.map((field) => (
              <FieldChip key={`${field.kind}:${field.name}`} field={field} />
            ))}
          </div>
        );
      })}
      {filtered.length === 0 && <p className="hint">No fields match.</p>}
    </div>
  );
}

function FieldChip({ field }: { field: DesignerField }) {
  const { attributes, listeners, setNodeRef } = useDraggable({
    id: `field:${field.table}:${field.kind}:${field.name}`,
    data: { field },
  });
  return (
    <button
      ref={setNodeRef}
      type="button"
      className={`dp-field${field.kind === "measure" ? " measure" : ""}`}
      {...listeners}
      {...attributes}
    >
      <span className="dp-field-icon">{field.kind === "measure" ? "Σ" : "≡"}</span>
      {field.name}
    </button>
  );
}
