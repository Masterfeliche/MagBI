/** Dataset creation wizard — pick connection, browse tables, create dataset. */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { apiFetch } from "../shared/api";

interface Connection {
  id: string;
  name: string;
  kind: string;
}

interface TableInfo {
  schema: string;
  name: string;
  columns: { name: string; type: string }[];
}

type Step = "connection" | "tables" | "name";

export function DatasetWizard() {
  const { workspaceId } = useParams();
  const navigate = useNavigate();

  const [step, setStep] = useState<Step>("connection");
  const [connections, setConnections] = useState<Connection[]>([]);
  const [selectedConn, setSelectedConn] = useState<string>("");
  const [schemas, setSchemas] = useState<string[]>([]);
  const [selectedSchema, setSelectedSchema] = useState("");
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [selectedTables, setSelectedTables] = useState<Set<string>>(new Set());
  const [datasetName, setDatasetName] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch<Connection[]>(`/workspaces/${workspaceId}/connections`)
      .then(setConnections)
      .catch(() => setError("Failed to load connections"));
  }, [workspaceId]);

  async function loadSchemas(connId: string) {
    setLoading(true);
    setError("");
    try {
      const res = await apiFetch<{ schemas: string[] }>(
        `/workspaces/${workspaceId}/connections/${connId}/schemas`,
      );
      setSchemas(res.schemas);
      if (res.schemas.length === 1) {
        setSelectedSchema(res.schemas[0]);
        await loadTables(connId, res.schemas[0]);
      }
    } catch {
      setError("Failed to load schemas");
    } finally {
      setLoading(false);
    }
  }

  async function loadTables(connId: string, schema: string) {
    setLoading(true);
    setError("");
    try {
      const res = await apiFetch<{ tables: TableInfo[] }>(
        `/workspaces/${workspaceId}/connections/${connId}/tables?schema=${encodeURIComponent(schema)}`,
      );
      setTables(res.tables);
    } catch {
      setError("Failed to load tables");
    } finally {
      setLoading(false);
    }
  }

  function toggleTable(fullName: string) {
    setSelectedTables((prev) => {
      const next = new Set(prev);
      if (next.has(fullName)) next.delete(fullName);
      else next.add(fullName);
      return next;
    });
  }

  async function createDataset() {
    if (!datasetName.trim() || selectedTables.size === 0) return;
    setSaving(true);
    setError("");
    try {
      const importTables = Array.from(selectedTables).map((t) => {
        const [schema, ...rest] = t.split(".");
        return { schema, name: rest.join(".") };
      });
      const ds = await apiFetch<{ id: string }>(`/workspaces/${workspaceId}/datasets`, {
        method: "POST",
        body: JSON.stringify({
          name: datasetName.trim(),
          import_spec: {
            connection_id: selectedConn,
            tables: importTables,
          },
        }),
      });
      navigate(`/workspaces/${workspaceId}/datasets/${ds.id}/designer`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setSaving(false);
    }
  }

  const steps: { key: Step; label: string; num: number }[] = [
    { key: "connection", label: "Connection", num: 1 },
    { key: "tables", label: "Tables", num: 2 },
    { key: "name", label: "Name & Create", num: 3 },
  ];

  const stepIndex = steps.findIndex((s) => s.key === step);

  return (
    <div className="ws-page">
      <div className="ws-header">
        <h1>New Dataset</h1>
      </div>

      <div className="wizard-steps">
        {steps.map((s, i) => (
          <div
            key={s.key}
            className={`wizard-step ${i === stepIndex ? "active" : i < stepIndex ? "done" : ""}`}
          >
            <span className="wizard-step-num">
              {i < stepIndex ? "✓" : s.num}
            </span>
            {s.label}
            {i < steps.length - 1 && <span className="wizard-step-arrow">→</span>}
          </div>
        ))}
      </div>

      {error && <p className="ws-error">{error}</p>}

      {step === "connection" && (
        <div className="panel">
          <h3 style={{ margin: "0 0 12px", fontSize: 15 }}>Select a connection</h3>
          {connections.length === 0 ? (
            <div className="ws-empty">
              <p>No connections available.</p>
              <button
                className="ws-btn primary"
                onClick={() => navigate(`/workspaces/${workspaceId}/connections/new`)}
              >
                + New connection
              </button>
            </div>
          ) : (
            <div className="ws-grid">
              {connections.map((c) => (
                <div
                  key={c.id}
                  className={`ws-card ${selectedConn === c.id ? "selected" : ""}`}
                  style={selectedConn === c.id ? { borderColor: "var(--blue)" } : undefined}
                  onClick={() => setSelectedConn(c.id)}
                >
                  <div>
                    <div className="ws-card-name">{c.name}</div>
                    <div style={{ fontSize: 12, color: "var(--text2)", marginTop: 4 }}>{c.kind}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
          <div className="form-actions">
            <button className="ws-btn" onClick={() => navigate(`/workspaces/${workspaceId}`)}>
              Cancel
            </button>
            <button
              className="ws-btn primary"
              disabled={!selectedConn}
              onClick={() => {
                loadSchemas(selectedConn);
                setStep("tables");
              }}
            >
              Next →
            </button>
          </div>
        </div>
      )}

      {step === "tables" && (
        <div className="panel">
          <h3 style={{ margin: "0 0 12px", fontSize: 15 }}>Select tables to import</h3>

          {schemas.length > 1 && (
            <div className="form-group" style={{ marginBottom: 16 }}>
              <label>Schema</label>
              <select
                value={selectedSchema}
                onChange={(e) => {
                  setSelectedSchema(e.target.value);
                  loadTables(selectedConn, e.target.value);
                }}
              >
                <option value="">Select schema…</option>
                {schemas.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
          )}

          {loading ? (
            <p className="ws-loading">Loading tables…</p>
          ) : tables.length === 0 ? (
            <p className="ws-hint" style={{ padding: "20px 0" }}>
              {selectedSchema ? "No tables found in this schema." : "Select a schema above."}
            </p>
          ) : (
            <div className="table-browser">
              {tables.map((t) => {
                const fullName = `${t.schema}.${t.name}`;
                const checked = selectedTables.has(fullName);
                return (
                  <div
                    key={fullName}
                    className="table-browser-row"
                    onClick={() => toggleTable(fullName)}
                  >
                    <input type="checkbox" checked={checked} readOnly />
                    <span style={{ fontWeight: 500 }}>{t.name}</span>
                    <span style={{ fontSize: 12, color: "var(--text3)" }}>
                      {t.columns?.length ?? 0} columns
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          <div className="form-actions">
            <button className="ws-btn" onClick={() => setStep("connection")}>
              ← Back
            </button>
            <button
              className="ws-btn primary"
              disabled={selectedTables.size === 0}
              onClick={() => setStep("name")}
            >
              Next →
            </button>
          </div>
        </div>
      )}

      {step === "name" && (
        <div className="panel" style={{ maxWidth: 480 }}>
          <div className="form-group">
            <label>Dataset name</label>
            <input
              type="text"
              value={datasetName}
              onChange={(e) => setDatasetName(e.target.value)}
              placeholder="e.g. Sales Analytics"
              autoFocus
            />
          </div>

          <p style={{ fontSize: 13, color: "var(--text2)", margin: "0 0 16px" }}>
            {selectedTables.size} table{selectedTables.size !== 1 ? "s" : ""} selected
          </p>

          <div className="form-actions">
            <button className="ws-btn" onClick={() => setStep("tables")}>
              ← Back
            </button>
            <button
              className="ws-btn primary"
              disabled={saving || !datasetName.trim()}
              onClick={createDataset}
            >
              {saving ? "Creating…" : "Create Dataset"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
