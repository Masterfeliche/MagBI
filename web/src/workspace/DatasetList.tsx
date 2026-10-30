/** Dataset listing within a workspace. */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiFetch } from "../shared/api";
import type { DatasetSummary } from "../types/api";

function fmtDate(iso?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function DatasetList({ workspaceId }: { workspaceId: string }) {
  const navigate = useNavigate();
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch<DatasetSummary[]>(`/workspaces/${workspaceId}/datasets`)
      .then(setDatasets)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [workspaceId]);

  if (loading) return <p className="ws-loading">Loading datasets...</p>;
  if (error) return <p className="ws-error">{error}</p>;
  if (datasets.length === 0) {
    return (
      <div className="ws-empty">
        <p>No datasets yet.</p>
        <p className="ws-hint">Create a dataset by connecting to a data source.</p>
      </div>
    );
  }

  return (
    <table className="ws-table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Mode</th>
          <th>Updated</th>
        </tr>
      </thead>
      <tbody>
        {datasets.map((ds) => (
          <tr key={ds.id}>
            <td>
              <button
                className="ws-link"
                onClick={() => navigate(`/workspaces/${workspaceId}/datasets/${ds.id}/designer`)}
              >
                {ds.name}
              </button>
            </td>
            <td className="ws-muted">{ds.mode ?? "import"}</td>
            <td className="ws-muted">{fmtDate(ds.updated_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
