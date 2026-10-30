/** Report listing within a workspace — open in designer or view mode. */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiFetch } from "../shared/api";
import type { ReportSummary } from "../types/api";

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ReportList({ workspaceId }: { workspaceId: string }) {
  const navigate = useNavigate();
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch<ReportSummary[]>(`/workspaces/${workspaceId}/reports`)
      .then(setReports)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [workspaceId]);

  if (loading) return <p className="ws-loading">Loading reports...</p>;
  if (error) return <p className="ws-error">{error}</p>;
  if (reports.length === 0) {
    return (
      <div className="ws-empty">
        <p>No reports yet.</p>
        <p className="ws-hint">Reports are created when you publish a dashboard from the designer.</p>
      </div>
    );
  }

  return (
    <table className="ws-table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Dataset</th>
          <th>Updated</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {reports.map((r) => (
          <tr key={r.id}>
            <td>
              <button
                className="ws-link"
                onClick={() => navigate(`/workspaces/${workspaceId}/reports/${r.id}/view`)}
              >
                {r.name}
              </button>
            </td>
            <td className="ws-muted">{(r.dataset_id ?? "").slice(0, 8)}</td>
            <td className="ws-muted">{r.updated_at ? fmtDate(r.updated_at) : "—"}</td>
            <td>
              <button
                type="button"
                className="ws-btn small"
                onClick={() => navigate(`/workspaces/${workspaceId}/reports/${r.id}/view`)}
              >
                View
              </button>{" "}
              <button
                type="button"
                className="ws-btn small"
                onClick={() =>
                  navigate(`/workspaces/${workspaceId}/datasets/${r.dataset_id}/designer?report=${r.id}`)
                }
              >
                Open in designer
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
