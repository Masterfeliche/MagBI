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

export function FieldKindIcon({ kind }: { kind: DesignerField["kind"] }) {
  if (kind === "measure") {
    return (
      <svg
        className="dp-field-icon"
        viewBox="0 0 16 16"
        width="12"
        height="12"
        aria-label="Measure"
      >
        <title>Measure</title>
        <rect x="2.5" y="1.5" width="11" height="13" rx="1.5" fill="none" stroke="currentColor" />
        <path d="M5 5h6M5 8h2.5M8.5 8H11M5 11h2.5M8.5 11H11" fill="none" stroke="currentColor" />
      </svg>
    );
  }
  return (
    <span className="dp-field-icon" title="Column" aria-label="Column">
      ≡
    </span>
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
      <FieldKindIcon kind={field.kind} />
      {field.name}
    </button>
  );
}
