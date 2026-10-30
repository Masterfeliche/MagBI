/** DAX-lite measure editor — name, home table, and expression. */

import Editor from "@monaco-editor/react";
import { useState } from "react";

import { adaptDataset, type DesignerTable } from "../designer/model";
import { apiFetch } from "../shared/api";
import "../workspace/workspace.css";

export function MeasureEditor({
  workspaceId,
  datasetId,
  modelVersion,
  tables,
  onClose,
  onSaved,
}: {
  workspaceId: string;
  datasetId: string;
  modelVersion: number;
  tables: DesignerTable[];
  onClose: () => void;
  onSaved: (tables: DesignerTable[], modelVersion: number) => void;
}) {
  const [name, setName] = useState("New Measure");
  const [table, setTable] = useState(tables[0]?.name ?? "");
  const [expression, setExpression] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    if (!table || !name.trim() || !expression.trim()) {
      setError("Name, table, and expression are required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const body = await apiFetch<{ model_version: number; definition: unknown }>(
        `/workspaces/${workspaceId}/datasets/${datasetId}/definition/measures`,
        {
          method: "POST",
          body: JSON.stringify({
            model_version: modelVersion,
            table,
            measure: { name: name.trim(), expression: expression.trim() },
          }),
        },
      );
      onSaved(adaptDataset(body.definition), body.model_version);
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not save measure");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal measure-editor" onClick={(event) => event.stopPropagation()}>
        <h3>New measure</h3>
        {error && <p className="ws-error">{error}</p>}
        <div className="form-row">
          <label htmlFor="measure-name">Name</label>
          <input
            id="measure-name"
            className="ws-input"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <div className="form-row">
          <label htmlFor="measure-table">Table</label>
          <select
            id="measure-table"
            className="ws-input"
            value={table}
            onChange={(event) => setTable(event.target.value)}
          >
            {tables.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        <div className="form-row">
          <label htmlFor="measure-dax">DAX</label>
          <div className="measure-dax">
            <Editor
              height="180px"
              defaultLanguage="plaintext"
              value={expression}
              onChange={(value) => setExpression(value ?? "")}
              options={{ minimap: { enabled: false }, fontSize: 13, wordWrap: "on" }}
            />
          </div>
        </div>
        <div className="form-actions">
          <button type="button" className="ws-btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="ws-btn primary" disabled={saving} onClick={() => void save()}>
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
