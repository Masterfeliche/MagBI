/** ECharts and TanStack views for the six visuals that draw a query result. */

import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import ReactECharts from "echarts-for-react";
import { useEffect, useMemo, useState } from "react";

import { apiFetch } from "../shared/api";
import type { DSR } from "../types/query";
import type { FilterDefinition, VisualDefinition } from "../types/report";
import { visualSpec } from "./catalog";
import { buildQuery } from "./query";
import { renderModel, type CartesianModel, type PieModel, type RenderModel } from "./render";

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
  return <Drawn model={renderModel(visual.type, dsr)} title={title} color={color} onCategory={onCategory} />;
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

function Drawn({
  model,
  title,
  color,
  onCategory,
}: {
  model: RenderModel;
  title: string;
  color: string;
  onCategory?: (category: string) => void;
}) {
  if (model.kind === "note") {
    return (
      <div className="note">
        {title && <strong>{title}</strong>}
        <div>{model.message}</div>
      </div>
    );
  }
  if (model.kind === "card") {
    return (
      <div className="card-value">
        {title && <span className="visual-label">{title}</span>}
        {model.value}
      </div>
    );
  }
  if (model.kind === "table") return <DataTable columns={model.columns} rows={model.rows} />;
  if (model.kind === "pie") return <PieChart model={model} title={title} color={color} onCategory={onCategory} />;
  return <CartesianChart model={model} title={title} color={color} onCategory={onCategory} />;
}

function CartesianChart({
  model,
  title,
  color,
  onCategory,
}: {
  model: CartesianModel;
  title: string;
  color: string;
  onCategory?: (category: string) => void;
}) {
  const horizontal = model.orientation === "bar";
  const option = {
    color: [color],
    title: title ? { text: title, left: 8, textStyle: { fontSize: 14, fontWeight: 600 } } : undefined,
    tooltip: { trigger: "axis" as const },
    grid: { left: 48, right: 16, top: title ? 36 : 16, bottom: 32 },
    xAxis: horizontal ? { type: "value" as const } : { type: "category" as const, data: model.categories },
    yAxis: horizontal ? { type: "category" as const, data: model.categories } : { type: "value" as const },
    series: model.series.map((series) => ({
      type: model.orientation === "line" ? ("line" as const) : ("bar" as const),
      name: series.name,
      data: series.values,
    })),
  };
  return (
    <ReactECharts
      option={option}
      style={{ height: "100%", width: "100%" }}
      onEvents={{
        click: (params: { name?: string }) => {
          if (params.name && onCategory) onCategory(params.name);
        },
      }}
    />
  );
}

function PieChart({
  model,
  title,
  color,
  onCategory,
}: {
  model: PieModel;
  title: string;
  color: string;
  onCategory?: (category: string) => void;
}) {
  const option = {
    color: [color, "#12239E", "#E66C37", "#6B007B", "#E044A7", "#744EC2"],
    title: title ? { text: title, left: 8, textStyle: { fontSize: 14, fontWeight: 600 } } : undefined,
    tooltip: { trigger: "item" as const },
    series: [{ type: "pie" as const, radius: "70%", data: model.slices }],
  };
  return (
    <ReactECharts
      option={option}
      style={{ height: "100%", width: "100%" }}
      onEvents={{
        click: (params: { name?: string }) => {
          if (params.name && onCategory) onCategory(params.name);
        },
      }}
    />
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
