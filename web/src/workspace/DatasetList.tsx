/** Dataset listing within a workspace. */
import { Fragment, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiFetch } from "../shared/api";
import type { DatasetSummary } from "../types/api";
import { RefreshPanel } from "./RefreshPanel";

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
  const [refreshId, setRefreshId] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<DatasetSummary[]>(`/workspaces/${workspaceId}/datasets`)
      .then(setDatasets)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [workspaceId]);

  if (loading) return <p className="ws-loading">Loading datasets...</p>;
  if (error) {
    return (
      <p className="ws-error">
        {error}{" "}
        <button type="button" className="ws-btn small" onClick={() => window.location.reload()}>Retry</button>
      </p>
    );
  }
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
          <th></th>
        </tr>
      </thead>
      <tbody>
        {datasets.map((ds) => (
          <Fragment key={ds.id}>
            <tr>
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
              <td>
                <button type="button" className="ws-btn small" onClick={() => setRefreshId(refreshId === ds.id ? null : ds.id)}>
                  Refresh
                </button>
              </td>
            </tr>
            {refreshId === ds.id && (
              <tr key={`${ds.id}-refresh`}>
                <td colSpan={4}>
                  <RefreshPanel workspaceId={workspaceId} datasetId={ds.id} />
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}
