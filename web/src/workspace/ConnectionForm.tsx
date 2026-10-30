import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { apiFetch } from "../shared/api";

interface TestResult {
  ok: boolean;
  server_version?: string;
  error?: string;
}

export function ConnectionForm() {
  const { workspaceId } = useParams();
  const navigate = useNavigate();
  const [kinds, setKinds] = useState<string[]>([]);
  const [kind, setKind] = useState("sqlserver");
  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState(1433);
  const [database, setDatabase] = useState("");
  const [authentication, setAuthentication] = useState<"sql" | "integrated">("sql");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [encrypt, setEncrypt] = useState(true);
  const [trustCert, setTrustCert] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch<{ kinds: string[] }>("/connection-kinds")
      .then((r) => setKinds(r.kinds))
      .catch(() => setKinds(["sqlserver"]));
  }, []);

  function buildConfig() {
    return {
      host,
      port,
      database,
      authentication,
      ...(authentication === "sql" ? { username, password } : {}),
      encrypt,
      trust_server_certificate: trustCert,
    };
  }

  async function testConnection() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await apiFetch<TestResult>(
        `/workspaces/${workspaceId}/connections/test`,
        { method: "POST", body: JSON.stringify({ kind, config: buildConfig() }) },
      );
      setTestResult(result);
    } catch (err: unknown) {
      setTestResult({ ok: false, error: err instanceof Error ? err.message : "Test failed" });
    } finally {
      setTesting(false);
    }
  }

  async function save() {
    if (!name.trim() || !host.trim() || !database.trim()) {
      setError("Name, host, and database are required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await apiFetch(`/workspaces/${workspaceId}/connections`, {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), kind, config: buildConfig() }),
      });
      navigate(`/workspaces/${workspaceId}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="connection-form">
      <h2>New Connection</h2>

      <div className="form-group">
        <label>Connection Name</label>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. MSD ERP Production" />
      </div>

      <div className="form-group">
        <label>Type</label>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {kinds.map((k) => (
            <option key={k} value={k}>{k === "sqlserver" ? "SQL Server" : k}</option>
          ))}
        </select>
      </div>

      <div className="form-divider" />

      <div className="form-row">
        <div className="form-group" style={{ flex: 3 }}>
          <label>Host / Server</label>
          <input type="text" value={host} onChange={(e) => setHost(e.target.value)} placeholder="e.g. 192.168.1.100 or server.local" />
        </div>
        <div className="form-group" style={{ flex: 1 }}>
          <label>Port</label>
          <input type="number" value={port} onChange={(e) => setPort(Number(e.target.value))} />
        </div>
      </div>

      <div className="form-group">
        <label>Database</label>
        <input type="text" value={database} onChange={(e) => setDatabase(e.target.value)} placeholder="e.g. MSD_ERP" />
      </div>

      <div className="form-group">
        <label>Authentication</label>
        <select value={authentication} onChange={(e) => setAuthentication(e.target.value as "sql" | "integrated")}>
          <option value="sql">SQL Server Authentication</option>
          <option value="integrated">Windows Authentication</option>
        </select>
      </div>

      {authentication === "sql" && (
        <div className="form-row">
          <div className="form-group" style={{ flex: 1 }}>
            <label>Username</label>
            <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} />
          </div>
          <div className="form-group" style={{ flex: 1 }}>
            <label>Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
        </div>
      )}

      <div className="form-row">
        <label className="form-toggle">
          <input type="checkbox" checked={encrypt} onChange={(e) => setEncrypt(e.target.checked)} />
          Encrypt connection
        </label>
        <label className="form-toggle">
          <input type="checkbox" checked={trustCert} onChange={(e) => setTrustCert(e.target.checked)} />
          Trust server certificate
        </label>
      </div>

      <div className="form-divider" />

      {testResult && (
        <div className={`test-result ${testResult.ok ? "success" : "failure"}`}>
          {testResult.ok
            ? `Connected successfully${testResult.server_version ? ` — ${testResult.server_version}` : ""}`
            : `Connection failed: ${testResult.error}`}
        </div>
      )}

      {error && <div className="test-result failure">{error}</div>}

      <div className="form-actions">
        <button className="btn btn-outline" onClick={() => navigate(`/workspaces/${workspaceId}`)}>
          Cancel
        </button>
        <button className="btn btn-outline" onClick={testConnection} disabled={testing || !host || !database}>
          {testing ? "Testing…" : "Test Connection"}
        </button>
        <button className="btn btn-primary" onClick={save} disabled={saving || !name.trim()}>
          {saving ? "Saving…" : "Save Connection"}
        </button>
      </div>
    </div>
  );
}
