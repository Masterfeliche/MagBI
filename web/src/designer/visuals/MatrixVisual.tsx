import { useEffect, useMemo, useState } from "react";

import { apiFetch } from "../../shared/api";
import type { DSR } from "../../types/query";
import type { FilterDefinition, VisualDefinition } from "../../types/report";
import { formatMeasure } from "../formatChart";
import { buildMatrix, expandablePaths, matrixQueries, TOTAL, visibleRows, type Matrix } from "../matrix";
import { useDesignerStore } from "../store";

/**
 * Rows in a hierarchy (up to three fields), an optional column field, and
 * values, with subtotals and totals. A row with children opens and closes with
 * its arrow; Expand all and Collapse all work on every level.
 */
export function MatrixVisual({
  visual,
  workspaceId,
  datasetId,
  filters,
  onCategory,
  highlightCategory,
}: {
  visual: VisualDefinition;
  workspaceId: string;
  datasetId: string;
  filters: FilterDefinition[];
  onCategory?: (category: string) => void;
  highlightCategory?: string;
}) {
  const roles = useDesignerStore((state) => state.viewAs?.roles);
  const queries = useMemo(() => matrixQueries(visual.wells, filters), [visual.wells, filters]);
  const rowCount = (visual.wells.rows ?? []).length;
  const hasColumn = (visual.wells.columns ?? []).length > 0;
  const [matrix, setMatrix] = useState<Matrix | null>(null);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const key = JSON.stringify([queries, roles]);

  useEffect(() => {
    if (queries.length === 0 || !workspaceId || !datasetId) {
      setMatrix(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      Promise.all(
        queries.map(({ level, query }) =>
          apiFetch<DSR>(`/workspaces/${workspaceId}/datasets/${datasetId}/query`, {
            method: "POST",
            body: JSON.stringify({ query, roles: roles ?? [] }),
            signal: controller.signal,
          }).then((dsr) => ({ level, dsr })),
        ),
      )
        .then((answers) => {
          if (controller.signal.aborted) return;
          setMatrix(buildMatrix(answers, rowCount, hasColumn));
          setError("");
        })
        .catch((reason: unknown) => {
          if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "the query failed");
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // `key` covers every input that changes the questions asked.
  }, [key, workspaceId, datasetId, rowCount, hasColumn]);

  const title = typeof visual.properties?.title === "string" ? visual.properties.title : "";
  if (error) return <div className="note">Couldn't load: {error}</div>;
  if (queries.length === 0) return <div className="note">Add rows or columns, and values.</div>;
  if (!matrix) return <div className="note">Loading…</div>;
  if (matrix.rows.length === 0 && matrix.total.size === 0) return <div className="note">Nothing recorded for this view yet</div>;

  const columnKeys = hasColumn ? [...matrix.columns, TOTAL] : [TOTAL];
  const shown = visibleRows(matrix.rows, expanded);
  const all = expandablePaths(matrix.rows);
  const toggle = (path: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  const cells = (values: Map<string, unknown[]>, strong = false) =>
    columnKeys.flatMap((column) =>
      matrix.measures.map((measure, index) => {
        const value = values.get(column)?.[index];
        return (
          <td key={`${column}-${index}`} className={strong ? "n total" : "n"}>
            {value == null ? "" : formatMeasure(value, measure.format)}
          </td>
        );
      }),
    );

  return (
    <div className="matrix-wrap">
      <div className="matrix-bar">
        {title && <strong>{title}</strong>}
        {all.length > 0 && (
          <span>
            <button type="button" onClick={() => setExpanded(new Set(all))}>Expand all</button>
            <button type="button" onClick={() => setExpanded(new Set())}>Collapse all</button>
          </span>
        )}
      </div>
      <div className="matrix-scroll">
        <table className="matrix">
          <thead>
            <tr>
              <th rowSpan={matrix.measures.length > 1 ? 2 : 1}>
                {(visual.wells.rows ?? []).map((field) => field.column ?? field.measure).join(" / ")}
              </th>
              {columnKeys.map((column) => (
                <th key={column} colSpan={matrix.measures.length} className="n">
                  {column === TOTAL ? "Total" : column}
                </th>
              ))}
            </tr>
            {matrix.measures.length > 1 && (
              <tr>
                {columnKeys.flatMap((column) =>
                  matrix.measures.map((measure) => (
                    <th key={`${column}-${measure.name}`} className="n">{measure.name}</th>
                  )),
                )}
              </tr>
            )}
          </thead>
          <tbody>
            {shown.map((node) => {
              const path = node.path.join("\u0001");
              const open = expanded.has(path);
              const dim = highlightCategory && node.depth === 0 && highlightCategory !== node.label;
              return (
                <tr key={path} className={dim ? "dim" : undefined}>
                  <th scope="row" style={{ paddingLeft: 8 + node.depth * 18 }}>
                    {node.children.length > 0 ? (
                      <button type="button" className="matrix-toggle" aria-expanded={open} aria-label={`${open ? "Collapse" : "Expand"} ${node.label}`} onClick={() => toggle(path)}>
                        {open ? "▾" : "▸"}
                      </button>
                    ) : (
                      <span className="matrix-toggle" />
                    )}
                    <button type="button" className="matrix-label" onClick={() => node.depth === 0 && onCategory?.(node.label)}>
                      {node.label}
                    </button>
                  </th>
                  {cells(node.cells, node.children.length > 0 && open)}
                </tr>
              );
            })}
            <tr className="matrix-total">
              <th scope="row">Total</th>
              {cells(matrix.total, true)}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
