/** Workspace listing and creation. */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiFetch } from "../shared/api";
import type { Workspace } from "../types/api";
import { SharedWithMe } from "./SharedWithMe";
import "./workspace.css";

export function WorkspaceList() {
  const navigate = useNavigate();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [sharedCount, setSharedCount] = useState(0);

  useEffect(() => {
    apiFetch<Workspace[]>("/workspaces")
      .then(setWorkspaces)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  async function create() {
    if (!newName.trim() || creating) return;
    setCreating(true);
    try {
      const ws = await apiFetch<Workspace>("/workspaces", {
        method: "POST",
        body: JSON.stringify({ name: newName.trim() }),
      });
      setWorkspaces((prev) => [...prev, ws]);
      setNewName("");
      setShowCreate(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Create failed");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="ws-page">
      <div className="ws-header">
        <h1>Workspaces</h1>
        <button className="ws-btn primary" onClick={() => setShowCreate(true)}>
          + New workspace
        </button>
      </div>

      {showCreate && (
        <div className="ws-create-form">
          <input
            className="ws-input"
            placeholder="Workspace name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && create()}
            autoFocus
          />
          <button className="ws-btn primary" onClick={create} disabled={creating}>
            {creating ? "Creating..." : "Create"}
          </button>
          <button className="ws-btn" onClick={() => { setShowCreate(false); setNewName(""); }}>
            Cancel
          </button>
        </div>
      )}

      {error && <p className="ws-error">{error}</p>}

      {loading ? (
        <p className="ws-loading">Loading workspaces...</p>
      ) : workspaces.length === 0 && sharedCount > 0 ? null : workspaces.length === 0 ? (
        <div className="ws-empty">
          <p>No workspaces yet.</p>
          <p className="ws-hint">Create one to get started with your dashboards.</p>
        </div>
      ) : (
        <div className="ws-grid">
          {workspaces.map((ws) => (
            <div key={ws.id} className="ws-card" onClick={() => navigate(`/workspaces/${ws.id}`)}>
              <div className="ws-card-name">{ws.name}</div>
              {ws.description && (
                <div style={{ fontSize: 12, color: "var(--text2)" }}>{ws.description}</div>
              )}
            </div>
          ))}
        </div>
      )}

      <SharedWithMe onFound={setSharedCount} />
    </div>
  );
}
