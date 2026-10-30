/** Schema and table picker shared by the dataset wizard and Get data. */

import { useEffect, useState } from "react";

import { apiFetch } from "../shared/api";

export interface BrowserTable {
  schema: string;
  name: string;
  columns?: { name: string; type?: string }[];
}

export function TableBrowser({
  workspaceId,
  connectionId,
  selected,
  onChange,
  taken = [],
}: {
  workspaceId: string;
  connectionId: string;
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  taken?: string[];
}) {
  const [schemas, setSchemas] = useState<string[]>([]);
  const [schema, setSchema] = useState("");
  const [tables, setTables] = useState<BrowserTable[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiFetch<{ schemas: string[] }>(`/workspaces/${workspaceId}/connections/${connectionId}/schemas`)
      .then(async (res) => {
        if (cancelled) return;
        setSchemas(res.schemas);
        const first = res.schemas[0] ?? "";
        setSchema(first);
        if (first) await load(first);
      })
      .catch(() => {
        if (!cancelled) setError("Failed to load schemas");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    async function load(nextSchema: string) {
      const res = await apiFetch<{ tables: BrowserTable[] }>(
        `/workspaces/${workspaceId}/connections/${connectionId}/tables?schema=${encodeURIComponent(nextSchema)}`,
      );
      if (!cancelled) setTables(res.tables);
    }
  }, [workspaceId, connectionId]);

  async function changeSchema(next: string) {
    setSchema(next);
    setLoading(true);
    setError("");
    try {
      const res = await apiFetch<{ tables: BrowserTable[] }>(
        `/workspaces/${workspaceId}/connections/${connectionId}/tables?schema=${encodeURIComponent(next)}`,
      );
      setTables(res.tables);
    } catch {
      setError("Failed to load tables");
    } finally {
      setLoading(false);
    }
  }

  function toggle(fullName: string) {
    const next = new Set(selected);
    if (next.has(fullName)) next.delete(fullName);
    else next.add(fullName);
    onChange(next);
  }

  const takenSet = new Set(taken.map((name) => name.toLowerCase()));

  return (
    <div className="table-browser">
      {error && <p className="ws-error">{error}</p>}
      {schemas.length > 1 && (
        <div className="table-browser-header">
          <select value={schema} onChange={(event) => void changeSchema(event.target.value)}>
            {schemas.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
      )}
      {loading ? (
        <p className="ws-loading">Loading tables...</p>
      ) : (
        tables.map((table) => {
          const fullName = `${table.schema}.${table.name}`;
          const already = takenSet.has(table.name.toLowerCase());
          return (
            <div key={fullName} className="table-browser-row" onClick={() => !already && toggle(fullName)}>
              <input type="checkbox" checked={already || selected.has(fullName)} readOnly disabled={already} />
              <span className="table-browser-name">{table.name}</span>
              <span className="table-browser-rows">{already ? "imported" : `${table.columns?.length ?? 0} columns`}</span>
            </div>
          );
        })
      )}
    </div>
  );
}
