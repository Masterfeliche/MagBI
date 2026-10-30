/** Choose an RLS role to apply to designer queries. */

import { useEffect, useState } from "react";

import { apiFetch } from "../shared/api";
import { useDesignerStore } from "../designer/store";
import "../workspace/workspace.css";

export function ViewAsDialog({
  workspaceId,
  datasetId,
  onClose,
}: {
  workspaceId: string;
  datasetId: string;
  onClose: () => void;
}) {
  const setViewAs = useDesignerStore((state) => state.setViewAs);
  const [roles, setRoles] = useState<string[]>([]);
  const [role, setRole] = useState("");
  const [user, setUser] = useState("");

  useEffect(() => {
    apiFetch<{ definition: { roles?: Array<{ name?: string }> } | null }>(
      `/workspaces/${workspaceId}/datasets/${datasetId}/definition`,
    ).then((body) => {
      const names = (body.definition?.roles ?? []).map((item) => String(item.name ?? "")).filter(Boolean);
      setRoles(names);
      setRole(names[0] ?? "");
    }).catch(() => setRoles([]));
  }, [workspaceId, datasetId]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <h3>View as</h3>
        <div className="form-row">
          <label htmlFor="view-as-role">Role</label>
          <select id="view-as-role" className="ws-input" value={role} onChange={(event) => setRole(event.target.value)}>
            {roles.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </div>
        <div className="form-row">
          <label htmlFor="view-as-user">User</label>
          <input id="view-as-user" className="ws-input" value={user} onChange={(event) => setUser(event.target.value)} />
        </div>
        <div className="form-actions">
          <button type="button" className="ws-btn" onClick={onClose}>Cancel</button>
          <button
            type="button"
            className="ws-btn"
            onClick={() => {
              setViewAs(null);
              onClose();
            }}
          >
            Stop viewing
          </button>
          <button
            type="button"
            className="ws-btn primary"
            disabled={!role}
            onClick={() => {
              setViewAs({ roles: [role], user: user.trim() || undefined });
              onClose();
            }}
          >
            View
          </button>
        </div>
      </div>
    </div>
  );
}
