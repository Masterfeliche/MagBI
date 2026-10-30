/** Data-fetching wrapper + registry dispatch for visual rendering. */

import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { useEffect, useMemo, useState } from "react";

import { apiFetch } from "../shared/api";
import type { DSR } from "../types/query";
import type { FilterDefinition, VisualDefinition } from "../types/report";
import { visualSpec } from "./catalog";
import { buildQuery } from "./query";
import { renderModel } from "./render";
import { VisualRenderer } from "./visuals/registry";

export function VisualView({
  visual,
  workspaceId,
  datasetId,
  filters,
  onCategory,
  onSlicer,
}: {
  visual: VisualDefinition;
  workspaceId: string;
  datasetId: string;
  filters: FilterDefinition[];
  onCategory?: (category: string) => void;
  onSlicer?: (value: string) => void;
}) {
  const spec = visualSpec(visual.type);
  const [dsr, setDsr] = useState<DSR | null>(null);
  const [error, setError] = useState("");
  const query = useMemo(() => buildQuery(visual.wells, filters), [visual.wells, filters]);
  const queryKey = JSON.stringify(query);
  const title = typeof visual.properties?.title === "string" ? visual.properties.title : "";
  const color = typeof visual.properties?.color === "string" ? visual.properties.color : "#118DFF";

  useEffect(() => {
    if (spec.renders === "map" || spec.renders === "none" || spec.renders === "slicer") return;
    if (query.select.length === 0 || !workspaceId || !datasetId) {
      setDsr(null);
      return;
    }
    let cancelled = false;
    setError("");
    apiFetch<DSR>(`/workspaces/${workspaceId}/datasets/${datasetId}/query`, {
      method: "POST",
      body: JSON.stringify({ query, roles: [] }),
    })
      .then((result) => {
        if (!cancelled) setDsr(result);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Query failed");
      });
    return () => {
      cancelled = true;
    };
  }, [spec.renders, queryKey, workspaceId, datasetId, query]);

  if (spec.renders === "slicer") {
    return <SlicerField visual={visual} onSlicer={onSlicer} />;
  }
  if (error) return <div className="note">{error}</div>;

  const model = renderModel(visual.type, dsr);
  if (model.kind === "table") return <DataTable columns={model.columns} rows={model.rows} />;
  return <VisualRenderer model={model} title={title} color={color} onCategory={onCategory} />;
}

function SlicerField({
  visual,
  onSlicer,
}: {
  visual: VisualDefinition;
  onSlicer?: (value: string) => void;
}) {
  const [value, setValue] = useState("");
  const binding = visual.wells.field?.[0];
  return (
    <form
      className="note"
      onPointerDown={(event) => event.stopPropagation()}
      onSubmit={(event) => {
        event.preventDefault();
        if (value.trim()) onSlicer?.(value.trim());
        setValue("");
      }}
    >
      <div>{binding?.column ? `${binding.table}.${binding.column}` : "Drop a field"}</div>
      <input value={value} onChange={(event) => setValue(event.target.value)} />
      <button type="submit">Apply</button>
    </form>
  );
}

function DataTable({ columns, rows }: { columns: string[]; rows: string[][] }) {
  const data = rows.map((row) =>
    Object.fromEntries(columns.map((name, index) => [name, row[index] ?? ""])),
  );
  const defs: ColumnDef<Record<string, string>>[] = columns.map((name) => ({
    accessorKey: name,
    header: name,
  }));
  const table = useReactTable({ data, columns: defs, getCoreRowModel: getCoreRowModel() });
  return (
    <table className="data-table">
      <thead>
        {table.getHeaderGroups().map((group) => (
          <tr key={group.id}>
            {group.headers.map((header) => (
              <th key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</th>
            ))}
          </tr>
        ))}
      </thead>
      <tbody>
        {table.getRowModel().rows.map((row) => (
          <tr key={row.id}>
            {row.getVisibleCells().map((cell) => (
              <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
