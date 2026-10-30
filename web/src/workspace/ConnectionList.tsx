/** Connection listing within a workspace — test, view details. */
import { useEffect, useState } from "react";

import { apiFetch } from "../shared/api";

interface ConnectionSummary {
  id: string;
  name: string;
  kind: string;
  config: Record<string, unknown>;
}

interface TestResult {
  ok: boolean;
  error?: string;
  server_version?: string;
}

export function ConnectionList({ workspaceId }: { workspaceId: string }) {
  const [connections, setConnections] = useState<ConnectionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});

  useEffect(() => {
    apiFetch<ConnectionSummary[]>(`/workspaces/${workspaceId}/connections`)
      .then(setConnections)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [workspaceId]);

  async function testConnection(conn: ConnectionSummary) {
    setTesting(conn.id);
    try {
      const result = await apiFetch<TestResult>(
        `/workspaces/${workspaceId}/connections/test`,
        {
          method: "POST",
          body: JSON.stringify({ kind: conn.kind, config: conn.config }),
        },
      );
      setTestResults((prev) => ({ ...prev, [conn.id]: result }));
    } catch (e: unknown) {
      setTestResults((prev) => ({
        ...prev,
        [conn.id]: { ok: false, error: e instanceof Error ? e.message : "Test failed" },
      }));
    } finally {
      setTesting(null);
    }
  }

  if (loading) return <p className="ws-loading">Loading connections...</p>;
  if (error) return <p className="ws-error">{error}</p>;
  if (connections.length === 0) {
    return (
      <div className="ws-empty">
        <p>No connections yet.</p>
        <p className="ws-hint">Add a connection to your SQL Server or other data source.</p>
      </div>
    );
  }

  return (
    <table className="ws-table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Type</th>
          <th>Host</th>
          <th>Database</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {connections.map((conn) => {
          const result = testResults[conn.id];
          return (
            <tr key={conn.id}>
              <td>{conn.name}</td>
              <td className="ws-muted">{conn.kind}</td>
              <td className="ws-muted">{String(conn.config.host ?? "")}</td>
              <td className="ws-muted">{String(conn.config.database ?? "")}</td>
              <td>
                <button
                  className="ws-btn small"
                  disabled={testing === conn.id}
                  onClick={() => testConnection(conn)}
                >
                  {testing === conn.id ? "Testing..." : "Test"}
                </button>
                {result && (
                  <span className={result.ok ? "ws-test-ok" : "ws-test-fail"}>
                    {result.ok
                      ? `Connected${result.server_version ? ` (${result.server_version})` : ""}`
                      : result.error ?? "Failed"}
                  </span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
