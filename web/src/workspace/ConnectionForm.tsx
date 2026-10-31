import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { apiFetch } from "../shared/api";
import {
  blankFields,
  buildConnectionConfig,
  KIND_LABELS,
  missingFields,
  needsLogin,
  type ConnectionFields,
} from "./connectionConfig";

/** POST /connections/test answers with ``success`` (see ConnectionTestResult on the server). */
interface TestResult {
  success: boolean;
  server_version?: string | null;
  error?: string | null;
}

export function ConnectionForm() {
  const { workspaceId } = useParams();
  const navigate = useNavigate();
  const [kinds, setKinds] = useState<string[]>([]);
  const [kind, setKind] = useState("sqlserver");
  const [name, setName] = useState("");
  const [fields, setFields] = useState<ConnectionFields>(blankFields("sqlserver"));
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch<{ kinds: string[] }>("/connection-kinds")
      .then((r) => setKinds(r.kinds))
      .catch(() => setKinds(["sqlserver"]));
  }, []);

  const set = <K extends keyof ConnectionFields>(key: K, value: ConnectionFields[K]) => setFields((prev) => ({ ...prev, [key]: value }));
  const missing = missingFields(kind, fields);
  const login = needsLogin(kind, fields);
  const web = kind === "odata";

  function pickKind(next: string) {
    setKind(next);
    setFields(blankFields(next));
    setTestResult(null);
    setError("");
  }

  async function testConnection() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await apiFetch<TestResult>(
        `/workspaces/${workspaceId}/connections/test`,
        { method: "POST", body: JSON.stringify({ kind, config: buildConnectionConfig(kind, fields) }) },
      );
      setTestResult(result);
    } catch (err: unknown) {
      setTestResult({ success: false, error: err instanceof Error ? err.message : "Test failed" });
    } finally {
      setTesting(false);
    }
  }

  async function save() {
    if (!name.trim() || missing.length > 0) {
      setError(`Still needed: ${[...(name.trim() ? [] : ["connection name"]), ...missing].join(", ")}`);
      return;
    }
    setSaving(true);
    setError("");
    try {
      await apiFetch(`/workspaces/${workspaceId}/connections`, {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), kind, config: buildConnectionConfig(kind, fields) }),
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
        <label htmlFor="conn-name">Connection Name</label>
        <input id="conn-name" type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. MSD ERP Production" />
      </div>

      <div className="form-group">
        <label htmlFor="conn-kind">Type</label>
        <select id="conn-kind" value={kind} onChange={(e) => pickKind(e.target.value)}>
          {kinds.map((k) => (
            <option key={k} value={k}>{KIND_LABELS[k] ?? k}</option>
          ))}
        </select>
      </div>

      <div className="form-divider" />

      {web ? (
        <>
          <div className="form-group">
            <label htmlFor="conn-format">Source</label>
            <select id="conn-format" value={fields.format} onChange={(e) => set("format", e.target.value as ConnectionFields["format"])}>
              <option value="odata">OData service: every entity set becomes a table</option>
              <option value="json">REST endpoint returning JSON: one table</option>
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="conn-url">{fields.format === "odata" ? "Service root URL" : "Endpoint URL"}</label>
            <input id="conn-url" type="text" value={fields.url} onChange={(e) => set("url", e.target.value)}
              placeholder={fields.format === "odata" ? "e.g. https://erp.example.com/odata/" : "e.g. https://api.example.com/v1/items"} />
          </div>
          {fields.format === "json" && (
            <>
              <div className="form-row">
                <div className="form-group" style={{ flex: 1 }}>
                  <label htmlFor="conn-table">Table name</label>
                  <input id="conn-table" type="text" value={fields.tableName} onChange={(e) => set("tableName", e.target.value)} />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label htmlFor="conn-records">Records path</label>
                  <input id="conn-records" type="text" value={fields.recordsPath} onChange={(e) => set("recordsPath", e.target.value)} placeholder="e.g. data.items (blank: the response is the list)" />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label htmlFor="conn-next">Next page path</label>
                  <input id="conn-next" type="text" value={fields.nextPath} onChange={(e) => set("nextPath", e.target.value)} placeholder="e.g. links.next (blank: one page)" />
                </div>
              </div>
              <div className="form-hint">Nested objects become columns joined by an underscore (Address_City); lists are kept as JSON text.</div>
            </>
          )}
          <div className="form-group">
            <label htmlFor="conn-auth">Authentication</label>
            <select id="conn-auth" value={fields.authentication} onChange={(e) => set("authentication", e.target.value)}>
              <option value="none">None (public)</option>
              <option value="basic">User name and password</option>
              <option value="bearer">Bearer token</option>
            </select>
          </div>
        </>
      ) : (
        <>
          <div className="form-row">
            <div className="form-group" style={{ flex: 3 }}>
              <label htmlFor="conn-host">Host / Server</label>
              <input id="conn-host" type="text" value={fields.host} onChange={(e) => set("host", e.target.value)} placeholder="e.g. 192.168.1.100 or server.local" />
            </div>
            <div className="form-group" style={{ flex: 1 }}>
              <label htmlFor="conn-port">Port</label>
              <input id="conn-port" type="number" value={fields.port} onChange={(e) => set("port", Number(e.target.value))} />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="conn-db">{kind === "mysql" ? "Database (optional: every database you can read is listed)" : "Database"}</label>
            <input id="conn-db" type="text" value={fields.database} onChange={(e) => set("database", e.target.value)} placeholder={kind === "sqlserver" ? "e.g. MSD_ERP" : "e.g. erp"} />
          </div>

          {kind === "sqlserver" && (
            <div className="form-group">
              <label htmlFor="conn-auth">Authentication</label>
              <select id="conn-auth" value={fields.authentication} onChange={(e) => set("authentication", e.target.value)}>
                <option value="sql">SQL Server Authentication</option>
                <option value="integrated">Windows Authentication</option>
              </select>
            </div>
          )}
        </>
      )}

      {login && (
        <div className="form-row">
          {!(web && fields.authentication === "bearer") && (
            <div className="form-group" style={{ flex: 1 }}>
              <label htmlFor="conn-user">Username</label>
              <input id="conn-user" type="text" value={fields.username} onChange={(e) => set("username", e.target.value)} />
            </div>
          )}
          <div className="form-group" style={{ flex: 1 }}>
            <label htmlFor="conn-secret">{web && fields.authentication === "bearer" ? "Token" : "Password"}</label>
            <input id="conn-secret" type="password" value={fields.password} onChange={(e) => set("password", e.target.value)} autoComplete="new-password" />
          </div>
        </div>
      )}

      {kind === "sqlserver" && (
        <div className="form-row">
          <label className="form-toggle">
            <input type="checkbox" checked={fields.encrypt} onChange={(e) => set("encrypt", e.target.checked)} />
            Encrypt connection
          </label>
          <label className="form-toggle">
            <input type="checkbox" checked={fields.trustCert} onChange={(e) => set("trustCert", e.target.checked)} />
            Trust server certificate
          </label>
        </div>
      )}
      {kind === "postgresql" && (
        <div className="form-group">
          <label htmlFor="conn-ssl">Encryption (SSL mode)</label>
          <select id="conn-ssl" value={fields.sslmode} onChange={(e) => set("sslmode", e.target.value)}>
            <option value="prefer">Prefer: encrypt when the server can</option>
            <option value="require">Require: always encrypt</option>
            <option value="verify-full">Verify: encrypt and check the certificate and host name</option>
            <option value="disable">Off</option>
          </select>
        </div>
      )}
      {kind === "mysql" && (
        <div className="form-row">
          <label className="form-toggle">
            <input type="checkbox" checked={fields.ssl} onChange={(e) => set("ssl", e.target.checked)} />
            Encrypt connection (SSL)
          </label>
        </div>
      )}
      {!web && <div className="form-hint">MagBI only reads: the session is read-only. A login that can only read is still best.</div>}

      <div className="form-divider" />

      {testResult && (
        <div className={`test-result ${testResult.success ? "success" : "failure"}`}>
          {testResult.success
            ? `Connected successfully${testResult.server_version ? ` — ${testResult.server_version}` : ""}`
            : `Connection failed: ${testResult.error}`}
        </div>
      )}

      {error && <div className="test-result failure">{error}</div>}
      {!name.trim() && <div className="form-hint">Enter a connection name to save.</div>}

      <div className="form-actions">
        <button className="btn btn-outline" onClick={() => navigate(`/workspaces/${workspaceId}`)}>
          Cancel
        </button>
        <button className="btn btn-outline" onClick={testConnection} disabled={testing || missing.length > 0}
          title={missing.length ? `Still needed: ${missing.join(", ")}` : undefined}>
          {testing ? "Testing…" : "Test Connection"}
        </button>
        <button className="btn btn-primary" onClick={save} disabled={saving || !name.trim()}>
          {saving ? "Saving…" : "Save Connection"}
        </button>
      </div>
    </div>
  );
}
