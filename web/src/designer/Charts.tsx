/** Data-fetching wrapper + registry dispatch for visual rendering. */

import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { useEffect, useMemo, useState } from "react";

import { apiFetch } from "../shared/api";
import type { DSR } from "../types/query";
import type { FilterDefinition, VisualDefinition } from "../types/report";
import { visualSpec } from "./catalog";
import type { FormatProps } from "./formatChart";
import { useDesignerStore } from "./store";
import { buildQuery } from "./query";
import { renderModel } from "./render";
import { VisualRenderer } from "./visuals/registry";

export function VisualView({
  visual,
  workspaceId,
  datasetId,
  filters,
  onCategory,
  onSlicerValues,
}: {
  visual: VisualDefinition;
  workspaceId: string;
  datasetId: string;
  filters: FilterDefinition[];
  onCategory?: (category: string) => void;
  onSlicerValues?: (values: string[]) => void;
}) {
  const spec = visualSpec(visual.type);
  const [dsr, setDsr] = useState<DSR | null>(null);
  const [error, setError] = useState("");
  const query = useMemo(() => buildQuery(visual.wells, filters), [visual.wells, filters]);
  const queryKey = JSON.stringify(query);
  const title = typeof visual.properties?.title === "string" ? visual.properties.title : "";
  const color = typeof visual.properties?.color === "string" ? visual.properties.color : "#118DFF";
  const palette = useDesignerStore((state) => state.report.theme?.colors);

  useEffect(() => {
    if (spec.renders === "map" || spec.renders === "none" || spec.renders === "slicer") return;
    if (query.select.length === 0 || !workspaceId || !datasetId) {
      setDsr(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setError("");
      apiFetch<DSR>(`/workspaces/${workspaceId}/datasets/${datasetId}/query`, {
        method: "POST",
        body: JSON.stringify({ query, roles: [] }),
        signal: controller.signal,
      })
        .then((result) => {
          if (!controller.signal.aborted) setDsr(result);
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted) return;
          setError(reason instanceof Error ? reason.message : "Query failed");
        });
    }, 300);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [spec.renders, queryKey, workspaceId, datasetId, query]);

  if (spec.renders === "slicer") {
    return (
      <SlicerField
        visual={visual}
        workspaceId={workspaceId}
        datasetId={datasetId}
        selected={selectedSlicerValues(filters, visual)}
        onChange={onSlicerValues}
      />
    );
  }
  if (error) return <div className="note">{error}</div>;

  const model = renderModel(visual.type, dsr);
  if (model.kind === "table") return <DataTable columns={model.columns} rows={model.rows} />;
  return (
    <VisualRenderer
      model={model}
      title={title}
      color={color}
      properties={(visual.properties ?? {}) as FormatProps}
      palette={palette}
      onCategory={onCategory}
    />
  );
}

function SlicerField({
  visual,
  workspaceId,
  datasetId,
  selected,
  onChange,
}: {
  visual: VisualDefinition;
  workspaceId: string;
  datasetId: string;
  selected: string[];
  onChange?: (values: string[]) => void;
}) {
  const [values, setValues] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const binding = visual.wells.field?.[0];

  useEffect(() => {
    if (!binding?.column || !workspaceId || !datasetId) {
      setValues([]);
      return;
    }
    let cancelled = false;
    apiFetch<DSR>(`/workspaces/${workspaceId}/datasets/${datasetId}/query`, {
      method: "POST",
      body: JSON.stringify({
        query: { from: [], select: [{ column: { table: binding.table, column: binding.column } }] },
        roles: [],
      }),
    })
      .then((result) => {
        if (cancelled) return;
        setValues([...new Set(result.rows.map((row) => (row[0] == null ? "" : String(row[0]))).filter(Boolean))]);
      })
      .catch(() => {
        if (!cancelled) setValues([]);
      });
    return () => {
      cancelled = true;
    };
  }, [binding?.column, binding?.table, workspaceId, datasetId]);

  const shown = values.filter((item) => item.toLowerCase().includes(query.toLowerCase()));
  return (
    <div className="slicer" onPointerDown={(event) => event.stopPropagation()}>
      <div>{binding?.column ?? "Drop a field"}</div>
      <input value={query} placeholder="Search" onChange={(event) => setQuery(event.target.value)} />
      {shown.map((item) => (
        <label key={item} className="slicer-row">
          <input
            type="checkbox"
            checked={selected.includes(item)}
            onChange={() => {
              const next = selected.includes(item) ? selected.filter((value) => value !== item) : [...selected, item];
              onChange?.(next);
            }}
          />
          {item}
        </label>
      ))}
    </div>
  );
}

function selectedSlicerValues(filters: FilterDefinition[], visual: VisualDefinition): string[] {
  const binding = visual.wells.field?.[0];
  if (!binding?.column) return [];
  const match = filters.find((filter) => filter.table === binding.table && filter.column === binding.column);
  const config = match?.config as { values?: unknown[] } | undefined;
  return Array.isArray(config?.values) ? config.values.map(String) : [];
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
