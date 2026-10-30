/** Ask the API for an embed token and show the iframe snippet. */

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { apiFetch } from "../shared/api";
import type { ReportSummary } from "../types/api";

export function EmbedPage() {
  const { workspaceId } = useParams();
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [reportId, setReportId] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [email, setEmail] = useState("viewer@example.com");
  const [name, setName] = useState("Viewer");
  const [result, setResult] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    setError("");
    apiFetch<ReportSummary[]>(`/workspaces/${workspaceId}/reports`)
      .then((rows) => {
        setReports(rows);
        setReportId(rows[0]?.id ?? "");
        setDatasetId(rows[0]?.dataset_id ?? "");
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load reports"))
      .finally(() => setLoading(false));
  }

  useEffect(load, [workspaceId]);

  async function createToken() {
    setError("");
    setResult("");
    try {
      const body = await apiFetch<{ token: string; reportUrls?: Record<string, string> }>("/embed/token", {
        method: "POST",
        body: JSON.stringify({
          userEmail: email,
          userName: name,
          reports: reportId ? [reportId] : [],
          datasets: datasetId ? [datasetId] : [],
          rls: { roles: [] },
        }),
      });
      const url = body.reportUrls?.[reportId] ?? `/embed/${reportId}`;
      setResult(`<iframe src="${url}?token=${body.token}"></iframe>`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "A service token is required to mint an embed token");
    }
  }

  if (loading) return <p className="ws-loading">Loading reports...</p>;
  return (
    <div className="ws-page">
      <div className="ws-header"><h1>Embed</h1></div>
      {error && (
        <p className="ws-error">
          {error} <button type="button" className="ws-btn small" onClick={load}>Retry</button>
        </p>
      )}
      {reports.length === 0 ? (
        <div className="ws-empty"><p>Publish a report before embedding it.</p></div>
      ) : (
        <div className="panel">
          <div className="form-group">
            <label>Report</label>
            <select
              value={reportId}
              onChange={(event) => {
                setReportId(event.target.value);
                setDatasetId(reports.find((report) => report.id === event.target.value)?.dataset_id ?? "");
              }}
            >
              {reports.map((report) => (
                <option key={report.id} value={report.id}>{report.name}</option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label>Viewer email</label>
            <input value={email} onChange={(event) => setEmail(event.target.value)} />
          </div>
          <div className="form-group">
            <label>Viewer name</label>
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <button type="button" className="ws-btn primary" onClick={() => void createToken()}>Create embed token</button>
          {result && <pre className="ws-hint">{result}</pre>}
        </div>
      )}
    </div>
  );
}
