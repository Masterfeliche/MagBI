/** Add source tables or a CSV/Excel file to an existing dataset. */

import { useEffect, useState } from "react";

import { apiFetch } from "../shared/api";
import { mergeImportTables, type SourceTable } from "./refreshPlan";
import { TableBrowser } from "./TableBrowser";
import "./workspace.css";

type Tab = "file" | "database";

export function tableNameFromFile(filename: string): string {
  const stem = filename.replace(/^.*[\\/]/, "").replace(/\.[^.]+$/, "");
  let cleaned = stem.replace(/[^A-Za-z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
  if (!cleaned) cleaned = "imported";
  if (/^\d/.test(cleaned)) cleaned = `t_${cleaned}`;
  return cleaned.slice(0, 128);
}

export function GetDataDialog({
  workspaceId,
  datasetId,
  onClose,
  onImported,
}: {
  workspaceId: string;
  datasetId: string;
  onClose: () => void;
  onImported: () => void;
}) {
  const [tab, setTab] = useState<Tab>("file");
  const [connectionId, setConnectionId] = useState("");
  const [taken, setTaken] = useState<string[]>([]);
  const [modelVersion, setModelVersion] = useState(1);
  const [definition, setDefinition] = useState<Record<string, unknown> | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [file, setFile] = useState<File | null>(null);
  const [tableName, setTableName] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiFetch<{ model_version: number; definition: Record<string, unknown> | null }>(
      `/workspaces/${workspaceId}/datasets/${datasetId}/definition`,
    )
      .then((body) => {
        const doc = body.definition ?? {};
        setDefinition(doc);
        setModelVersion(body.model_version);
        setConnectionId(typeof doc.connection_id === "string" ? doc.connection_id : "");
        const tables = Array.isArray(doc.tables) ? doc.tables : [];
        setTaken(tables.map((table) => String((table as { name?: string }).name ?? "")));
      })
      .catch(() => setError("This dataset has no import definition"));
  }, [workspaceId, datasetId]);

  async function addTables() {
    if (!definition) return;
    const picks: SourceTable[] = [...selected].map((full) => {
      const [schema, ...rest] = full.split(".");
      return { schema, name: rest.join(".") };
    });
    const merged = mergeImportTables(definition, picks);
    if (merged.added.length === 0) {
      setError("Choose a table that is not already imported");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await apiFetch(`/workspaces/${workspaceId}/datasets/${datasetId}/definition`, {
        method: "PUT",
        body: JSON.stringify({ model_version: modelVersion, definition: merged.definition }),
      });
      await apiFetch(`/workspaces/${workspaceId}/datasets/${datasetId}/refresh`, { method: "POST" });
      onImported();
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not add tables");
    } finally {
      setSaving(false);
    }
  }

  async function uploadFile() {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    const name = tableName.trim() || tableNameFromFile(file.name);
    if (name) body.append("table_name", name);
    setSaving(true);
    setError("");
    try {
      await apiFetch(`/workspaces/${workspaceId}/datasets/${datasetId}/upload`, {
        method: "POST",
        body,
      });
      onImported();
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not upload file");
    } finally {
      setSaving(false);
    }
  }

  const canUpload = !!file && !saving;
  const canImport = selected.size > 0 && !saving;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <h3>Get data</h3>
        <div className="modal-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            className={`modal-tab${tab === "file" ? " active" : ""}`}
            aria-selected={tab === "file"}
            onClick={() => setTab("file")}
          >
            File
          </button>
          <button
            type="button"
            role="tab"
            className={`modal-tab${tab === "database" ? " active" : ""}`}
            aria-selected={tab === "database"}
            onClick={() => setTab("database")}
          >
            Database
          </button>
        </div>
        {error && <p className="ws-error">{error}</p>}
        {tab === "file" ? (
          <>
            <div className="form-row">
              <label htmlFor="get-data-file">Excel or CSV</label>
              <input
                id="get-data-file"
                className="ws-input"
                type="file"
                accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                onChange={(event) => {
                  const next = event.target.files?.[0] ?? null;
                  setFile(next);
                  if (next) setTableName(tableNameFromFile(next.name));
                }}
              />
            </div>
            <div className="form-row">
              <label htmlFor="get-data-table">Table name</label>
              <input
                id="get-data-table"
                className="ws-input"
                value={tableName}
                onChange={(event) => setTableName(event.target.value)}
                placeholder="Ledger"
              />
            </div>
            <p className="ws-hint">Existing DuckDB tables stay in place. Re-uploading the same name replaces that table.</p>
            <div className="form-actions">
              <button type="button" className="ws-btn" onClick={onClose}>Cancel</button>
              <button type="button" className="ws-btn primary" disabled={!canUpload} onClick={() => void uploadFile()}>
                {saving ? "Uploading..." : "Upload"}
              </button>
            </div>
          </>
        ) : (
          <>
            {connectionId ? (
              <TableBrowser
                workspaceId={workspaceId}
                connectionId={connectionId}
                selected={selected}
                onChange={setSelected}
                taken={taken}
              />
            ) : (
              <p className="ws-hint">This dataset is not tied to a connection.</p>
            )}
            <div className="form-actions">
              <button type="button" className="ws-btn" onClick={onClose}>Cancel</button>
              <button type="button" className="ws-btn primary" disabled={!canImport} onClick={() => void addTables()}>
                {saving ? "Importing..." : "Add and refresh"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
