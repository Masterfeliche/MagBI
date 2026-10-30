/** Manage RLS roles stored on the dataset definition. */

import { useEffect, useState } from "react";

import { apiFetch } from "../shared/api";
import type { DesignerTable } from "../designer/model";
import "../workspace/workspace.css";

interface RoleDef {
  name: string;
  table_filters: Array<{ table: string; expression: string }>;
}

export function RlsRolesDialog({
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
  onSaved: (modelVersion: number) => void;
}) {
  const [roles, setRoles] = useState<RoleDef[]>([]);
  const [definition, setDefinition] = useState<Record<string, unknown>>({});
  const [name, setName] = useState("DepartmentAccess");
  const [table, setTable] = useState(tables[0]?.name ?? "");
  const [expression, setExpression] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [version, setVersion] = useState(modelVersion);

  useEffect(() => {
    apiFetch<{ model_version: number; definition: Record<string, unknown> | null }>(
      `/workspaces/${workspaceId}/datasets/${datasetId}/definition`,
    ).then((body) => {
      const doc = body.definition ?? {};
      setDefinition(doc);
      setVersion(body.model_version);
      setRoles(Array.isArray(doc.roles) ? (doc.roles as RoleDef[]) : []);
    }).catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load roles"));
  }, [workspaceId, datasetId]);

  async function save(next: RoleDef[]) {
    setSaving(true);
    setError("");
    try {
      const body = await apiFetch<{ model_version: number }>(
        `/workspaces/${workspaceId}/datasets/${datasetId}/definition`,
        {
          method: "PUT",
          body: JSON.stringify({
            model_version: version,
            definition: { ...definition, roles: next },
          }),
        },
      );
      setRoles(next);
      setVersion(body.model_version);
      onSaved(body.model_version);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not save roles");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <h3>Manage roles</h3>
        {error && <p className="ws-error">{error}</p>}
        {roles.map((role) => (
          <p key={role.name} className="ws-hint">
            {role.name}: {role.table_filters.map((filter) => `${filter.table} ${filter.expression}`).join("; ")}
          </p>
        ))}
        <div className="form-row">
          <label htmlFor="rls-name">Name</label>
          <input id="rls-name" className="ws-input" value={name} onChange={(event) => setName(event.target.value)} />
        </div>
        <div className="form-row">
          <label htmlFor="rls-table">Table</label>
          <select id="rls-table" className="ws-input" value={table} onChange={(event) => setTable(event.target.value)}>
            {tables.map((item) => (
              <option key={item.name} value={item.name}>{item.name}</option>
            ))}
          </select>
        </div>
        <div className="form-row">
          <label htmlFor="rls-dax">Filter</label>
          <input
            id="rls-dax"
            className="ws-input"
            value={expression}
            placeholder="[Dept] = &quot;HR&quot;"
            onChange={(event) => setExpression(event.target.value)}
          />
        </div>
        <div className="form-actions">
          <button type="button" className="ws-btn" onClick={onClose}>Close</button>
          <button
            type="button"
            className="ws-btn primary"
            disabled={saving || !name.trim() || !table || !expression.trim()}
            onClick={() =>
              void save([
                ...roles.filter((role) => role.name !== name.trim()),
                { name: name.trim(), table_filters: [{ table, expression: expression.trim() }] },
              ])
            }
          >
            {saving ? "Saving..." : "Save role"}
          </button>
        </div>
      </div>
    </div>
  );
}
