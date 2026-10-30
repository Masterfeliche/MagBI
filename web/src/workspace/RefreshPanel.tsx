/** Refresh now, poll until the job finishes, and show history. */

import { useEffect, useState } from "react";

import { apiFetch } from "../shared/api";
import { isRefreshDone } from "./refreshPlan";
import { ScheduleEditor } from "./ScheduleEditor";

interface RefreshJob {
  id: string;
  status: string;
  created_at: string;
  duration_seconds?: number | null;
  error?: string | null;
  result?: { rows?: number; row_count?: number } | null;
}

export function RefreshPanel({
  workspaceId,
  datasetId,
  onStatus,
}: {
  workspaceId: string;
  datasetId: string;
  onStatus?: (message: string) => void;
}) {
  const [history, setHistory] = useState<RefreshJob[]>([]);
  const [cron, setCron] = useState<string | null>(null);
  const [active, setActive] = useState<RefreshJob | null>(null);
  const [error, setError] = useState("");

  async function loadHistory() {
    const rows = await apiFetch<RefreshJob[]>(`/workspaces/${workspaceId}/datasets/${datasetId}/refresh/history`);
    setHistory(rows);
  }

  useEffect(() => {
    apiFetch<{ schedule_cron?: string | null }>(`/workspaces/${workspaceId}/datasets/${datasetId}`)
      .then((dataset) => setCron(dataset.schedule_cron ?? null))
      .catch(() => setError("Failed to load the dataset"));
    loadHistory().catch(() => setError("Failed to load refresh history"));
  }, [workspaceId, datasetId]);

  useEffect(() => {
    if (!active || isRefreshDone(active.status)) return;
    const timer = window.setInterval(() => {
      apiFetch<RefreshJob>(`/workspaces/${workspaceId}/datasets/${datasetId}/refresh/${active.id}`)
        .then((job) => {
          setActive(job);
          onStatus?.(`Refresh ${job.status}`);
          if (isRefreshDone(job.status)) {
            loadHistory().catch(() => undefined);
          }
        })
        .catch(() => setError("Lost the refresh status"));
    }, 3000);
    return () => window.clearInterval(timer);
  }, [active, workspaceId, datasetId, onStatus]);

  async function refreshNow() {
    setError("");
    try {
      const queued = await apiFetch<{ refresh_id: string; status: string }>(
        `/workspaces/${workspaceId}/datasets/${datasetId}/refresh`,
        { method: "POST" },
      );
      const job = { id: queued.refresh_id, status: queued.status, created_at: new Date().toISOString() };
      setActive(job);
      onStatus?.(`Refresh ${queued.status}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Refresh failed");
    }
  }

  return (
    <div className="refresh-panel">
      <div className="form-actions">
        <button type="button" className="ws-btn primary" onClick={() => void refreshNow()} disabled={!!active && !isRefreshDone(active.status)}>
          Refresh now
        </button>
        {active && <span className={`refresh-badge ${active.status}`}>{active.status}</span>}
      </div>
      {error && <p className="ws-error">{error}</p>}
      <ScheduleEditor workspaceId={workspaceId} datasetId={datasetId} cron={cron} onChange={setCron} />
      <table className="ws-table">
        <thead>
          <tr>
            <th>When</th>
            <th>Status</th>
            <th>Duration</th>
          </tr>
        </thead>
        <tbody>
          {history.map((job) => (
            <tr key={job.id}>
              <td>{new Date(job.created_at).toLocaleString()}</td>
              <td>{job.status}{job.error ? `: ${job.error}` : ""}</td>
              <td>{job.duration_seconds == null ? "—" : `${job.duration_seconds}s`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
