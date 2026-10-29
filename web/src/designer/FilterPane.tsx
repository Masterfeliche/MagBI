/** Page-level basic filters: equals and in. */

import { useState } from "react";

import type { FilterDefinition } from "../types/report";
import type { DesignerTable } from "./model";
import { pageFilter } from "./filters";

export function FilterPane({
  tables,
  filters,
  onChange,
}: {
  tables: DesignerTable[];
  filters: FilterDefinition[];
  onChange: (filters: FilterDefinition[]) => void;
}) {
  const columns = tables.flatMap((table) =>
    table.fields
      .filter((field) => field.kind === "column")
      .map((field) => ({ table: table.name, column: field.name })),
  );
  const [choice, setChoice] = useState(columns[0] ? `${columns[0].table}.${columns[0].column}` : "");
  const [operator, setOperator] = useState<"eq" | "in">("eq");
  const [raw, setRaw] = useState("");

  return (
    <div>
      <p className="pane-title">Filters on this page</p>
      {filters.map((filter, index) => (
        <div key={`${filter.table}.${filter.column}.${index}`} className="well">
          <span>
            {filter.table}.{filter.column}
          </span>
          <button type="button" onClick={() => onChange(filters.filter((_, item) => item !== index))}>
            Remove
          </button>
        </div>
      ))}
      <label className="stack">
        Field
        <select value={choice} onChange={(event) => setChoice(event.target.value)}>
          {columns.map((column) => {
            const key = `${column.table}.${column.column}`;
            return (
              <option key={key} value={key}>
                {key}
              </option>
            );
          })}
        </select>
      </label>
      <label className="stack">
        Operator
        <select value={operator} onChange={(event) => setOperator(event.target.value === "in" ? "in" : "eq")}>
          <option value="eq">is</option>
          <option value="in">is any of</option>
        </select>
      </label>
      <label className="stack">
        Values
        <input value={raw} onChange={(event) => setRaw(event.target.value)} />
      </label>
      <button
        type="button"
        onClick={() => {
          const [table, column] = choice.split(".");
          if (!table || !column || raw.trim() === "") return;
          onChange([...filters, pageFilter(table, column, operator, raw.trim())]);
          setRaw("");
        }}
      >
        Add filter
      </button>
    </div>
  );
}
