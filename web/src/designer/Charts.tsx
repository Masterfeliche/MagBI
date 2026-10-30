/** Data-fetching wrapper + registry dispatch for visual rendering. */

import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { useEffect, useMemo, useState } from "react";

import { apiFetch } from "../shared/api";
import type { DSR } from "../types/query";
import type { FilterDefinition, VisualDefinition } from "../types/report";
import { visualSpec } from "./catalog";
import { colorScale, dataBarWidth, statusColor } from "./condFormat";
import { slicerFilters, type SlicerMode } from "./slicer";
import type { FormatProps } from "./formatChart";
import { useDesignerStore } from "./store";
import { buildQuery } from "./query";
import { renderModel } from "./render";
import { ChainVisual, DonutVisual, formatCell, HeaderVisual, HeatVisual, ParetoVisual, StatusKpi } from "./StandardVisuals";
import { formatNumber } from "./formatChart";
import { rememberVisualData } from "./visualData";
import { VisualRenderer } from "./visuals/registry";

export function VisualView({
  visual,
  workspaceId,
  datasetId,
  filters,
  onCategory,
  onSlicerValues,
  highlightCategory,
  readOnly = false,
}: {
  visual: VisualDefinition;
  workspaceId: string;
  datasetId: string;
  filters: FilterDefinition[];
  onCategory?: (category: string) => void;
  onSlicerValues?: (values: string[], filters?: FilterDefinition[]) => void;
  highlightCategory?: string;
  readOnly?: boolean;
}) {
  const spec = visualSpec(visual.type);
  const [dsr, setDsr] = useState<DSR | null>(null);
  const [error, setError] = useState("");
  const drillLevel = Number(visual.properties?.drillLevel ?? 0);
  const query = useMemo(
    () => buildQuery(visual.wells, filters, { drillLevel }),
    [visual.wells, filters, drillLevel],
  );
  const queryKey = JSON.stringify(query);
  const title = typeof visual.properties?.title === "string" ? visual.properties.title : "";
  const color = typeof visual.properties?.color === "string" ? visual.properties.color : "#118DFF";
  const palette = useDesignerStore((state) => state.report.theme?.colors);
  const viewAs = useDesignerStore((state) => state.viewAs);
  const drillUp = useDesignerStore((state) => state.drillUp);
  const drillDown = useDesignerStore((state) => state.drillDown);

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
        body: JSON.stringify({ query, roles: viewAs?.roles ?? [] }),
        signal: controller.signal,
      })
        .then((result) => {
          if (controller.signal.aborted) return;
          setDsr(result);
          rememberVisualData(visual.id, result.columns.map((column) => column.name), result.rows);
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
  }, [spec.renders, queryKey, workspaceId, datasetId, query, viewAs, visual.id]);

  if (visual.type === "header") {
    return <HeaderVisual properties={visual.properties ?? {}} />;
  }
  if (spec.renders === "slicer") {
    return (
      <SlicerField
        visual={visual}
        workspaceId={workspaceId}
        datasetId={datasetId}
        selected={selectedSlicerValues(filters, visual)}
        readOnly={readOnly}
        onChange={(values, filters) => onSlicerValues?.(values, filters)}
      />
    );
  }
  if (error) return <div className="note">Couldn't load: {error}</div>;

  const hierarchy = visual.wells.hierarchy ?? [];
  const crumb = hierarchy.slice(0, drillLevel).map((item) => item.column ?? item.measure).filter(Boolean);
  const model = renderModel(visual.type, dsr, (visual.wells.tooltips ?? []).length);
  if (visual.type === "kpi" && model.kind === "card") {
    const tone = typeof visual.properties?.tone === "string" ? visual.properties.tone : "info";
    const context = typeof visual.properties?.context === "string" ? visual.properties.context : "";
    return <StatusKpi caption={title || "KPI"} value={formatNumber(model.value, { whole: true })} tone={tone} context={context} />;
  }
  if (visual.type === "chain" && model.kind === "table") return <ChainVisual model={model} />;
  if (visual.type === "donut" && model.kind === "pie") return <DonutVisual model={model} />;
  if (visual.type === "pareto" && model.kind === "cartesian") return <ParetoVisual model={model} />;
  if (visual.type === "heatmap" && model.kind === "table") return <HeatVisual model={model} />;
  if (model.kind === "table") {
    return (
      <DataTable
        columns={model.columns}
        rows={model.rows.map((row) => row.map((cell, index) => formatCell(model.columns[index] ?? "", cell)))}
        condFormat={typeof visual.properties?.condFormat === "string" ? visual.properties.condFormat : ""}
      />
    );
  }
  return (
    <>
      {hierarchy.length > 0 && (
        <div className="drill-crumb">
          {crumb.length > 0 && (
            <button type="button" onClick={() => drillUp(visual.id)}>Up</button>
          )}
          <span>{crumb.join(" / ") || "All"}</span>
        </div>
      )}
      <VisualRenderer
        model={model}
        title={title}
        color={color}
        properties={(visual.properties ?? {}) as FormatProps}
        palette={palette}
        onCategory={onCategory}
        onDrill={(category) => drillDown(visual.id, category)}
        highlightCategory={highlightCategory}
      />
    </>
  );
}

function SlicerField({
  visual,
  workspaceId,
  datasetId,
  selected,
  readOnly = false,
  onChange,
}: {
  visual: VisualDefinition;
  workspaceId: string;
  datasetId: string;
  selected: string[];
  readOnly?: boolean;
  onChange?: (values: string[], filters?: FilterDefinition[]) => void;
}) {
  const [values, setValues] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const binding = visual.wells.field?.[0];
  const viewAs = useDesignerStore((state) => state.viewAs);

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
        roles: viewAs?.roles ?? [],
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
  }, [binding?.column, binding?.table, workspaceId, datasetId, viewAs]);

  const shown = values.filter((item) => item.toLowerCase().includes(query.toLowerCase()));
  const setProperties = useDesignerStore((state) => state.setProperties);
  const mode = (visual.properties?.slicerMode as SlicerMode | undefined) ?? "list";
  const [min, setMin] = useState("");
  const [max, setMax] = useState("");

  function emit(nextSelected: string[], nextRange?: { min: string; max: string }) {
    if (!binding?.column) return;
    const filters = slicerFilters(binding.table, binding.column, mode, nextSelected, nextRange ?? { min, max });
    onChange?.(nextSelected, filters);
  }

  return (
    <div className="slicer" onPointerDown={(event) => event.stopPropagation()}>
      <div>{binding?.column ?? "Drop a field"}</div>
      {!readOnly && <select
        value={mode}
        onChange={(event) => setProperties(visual.id, { slicerMode: event.target.value })}
      >
        <option value="list">List</option>
        <option value="dropdown">Dropdown</option>
        <option value="range">Range</option>
      </select>}
      {mode === "dropdown" ? (
        <select
          value={selected[0] ?? ""}
          onChange={(event) => emit(event.target.value ? [event.target.value] : [])}
        >
          <option value="">All</option>
          {values.map((item) => (
            <option key={item} value={item}>{item}</option>
          ))}
        </select>
      ) : mode === "range" ? (
        <div className="slicer-range">
          <input value={min} placeholder="Min" onChange={(event) => setMin(event.target.value)} />
          <input value={max} placeholder="Max" onChange={(event) => setMax(event.target.value)} />
          <button type="button" onClick={() => emit([], { min, max })}>Apply</button>
        </div>
      ) : (
        <>
          <input value={query} placeholder="Search" onChange={(event) => setQuery(event.target.value)} />
          <label className="slicer-row">
            <input
              type="checkbox"
              checked={values.length > 0 && values.every((item) => selected.includes(item))}
              onChange={() => {
                const allOn = values.every((item) => selected.includes(item));
                emit(allOn ? [] : values);
              }}
            />
            Select all
          </label>
          {shown.map((item) => (
            <label key={item} className="slicer-row">
              <input
                type="checkbox"
                checked={selected.includes(item)}
                onChange={() => {
                  const next = selected.includes(item) ? selected.filter((value) => value !== item) : [...selected, item];
                  emit(next);
                }}
              />
              {item}
            </label>
          ))}
        </>
      )}
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

function DataTable({
  columns,
  rows,
  condFormat,
}: {
  columns: string[];
  rows: string[][];
  condFormat: string;
}) {
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
            {row.getVisibleCells().map((cell, index) => {
              const raw = String(cell.getValue() ?? "");
              const numeric = rows.map((item) => Number(item[index])).filter((item) => Number.isFinite(item));
              const n = Number(raw);
              const background =
                condFormat === "rules"
                  ? statusColor(raw)
                  : condFormat === "colorScale" && Number.isFinite(n)
                    ? colorScale(numeric, n)
                    : undefined;
              return (
                <td key={cell.id} style={{ background, position: "relative" }}>
                  {condFormat === "dataBar" && Number.isFinite(n) && (
                    <span className="data-bar" style={{ width: dataBarWidth(numeric, n) }} />
                  )}
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
