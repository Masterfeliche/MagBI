/** Add source tables to an existing dataset and start a refresh. */

import { useEffect, useState } from "react";

import { apiFetch } from "../shared/api";
import { mergeImportTables, type SourceTable } from "./refreshPlan";
import { TableBrowser } from "./TableBrowser";

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
  const [connectionId, setConnectionId] = useState("");
  const [taken, setTaken] = useState<string[]>([]);
  const [modelVersion, setModelVersion] = useState(1);
  const [definition, setDefinition] = useState<Record<string, unknown> | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
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

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <h3>Get data</h3>
        {error && <p className="ws-error">{error}</p>}
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
          <button type="button" className="ws-btn primary" disabled={saving || selected.size === 0} onClick={() => void addTables()}>
            {saving ? "Importing..." : "Add and refresh"}
          </button>
        </div>
      </div>
    </div>
  );
}
