/** Tables as boxes with relationship lines. Drag a column onto another to link them. */

import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { adaptDataset, type DesignerTable } from "../designer/model";
import { apiFetch } from "../shared/api";
import "../workspace/workspace.css";

interface Rel {
  id?: string;
  from?: { table: string; column: string };
  to?: { table: string; column: string };
}

export function ModelView() {
  const { workspaceId, datasetId } = useParams();
  const navigate = useNavigate();
  const [tables, setTables] = useState<DesignerTable[]>([]);
  const [rels, setRels] = useState<Rel[]>([]);
  const [version, setVersion] = useState(1);
  const [from, setFrom] = useState<{ table: string; column: string } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!workspaceId || !datasetId) return;
    apiFetch<{ model_version: number; definition: { tables?: unknown; relationships?: Rel[] } | null }>(
      `/workspaces/${workspaceId}/datasets/${datasetId}/definition`,
    ).then((body) => {
      setVersion(body.model_version);
      setTables(adaptDataset(body.definition));
      setRels(body.definition?.relationships ?? []);
    }).catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load model"));
  }, [workspaceId, datasetId]);

  async function link(to: { table: string; column: string }) {
    if (!from || !workspaceId || !datasetId || from.table === to.table) {
      setFrom(to);
      return;
    }
    try {
      const body = await apiFetch<{ model_version: number; definition: { relationships?: Rel[] } }>(
        `/workspaces/${workspaceId}/datasets/${datasetId}/definition/relationships`,
        {
          method: "POST",
          body: JSON.stringify({
            model_version: version,
            relationship: {
              from: { table: from.table, column: from.column },
              to: { table: to.table, column: to.column },
              cardinality: "many-to-one",
            },
          }),
        },
      );
      setVersion(body.model_version);
      setRels(body.definition.relationships ?? []);
      setFrom(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not save relationship");
    }
  }

  return (
    <div className="ws-page">
      <div className="ws-header">
        <h1>Model</h1>
        <button type="button" className="ws-btn" onClick={() => navigate(-1)}>Back</button>
      </div>
      {error && <p className="ws-error">{error}</p>}
      <p className="ws-hint">Click a column, then click the related column to save a many-to-one relationship.</p>
      <div className="model-grid">
        {tables.map((table) => (
          <div key={table.name} className="model-table">
            <strong>{table.name}</strong>
            {table.fields.filter((field) => field.kind === "column").map((field) => (
              <button
                key={field.name}
                type="button"
                className="ws-btn small"
                draggable
                onDragStart={() => setFrom({ table: table.name, column: field.name })}
                onDragOver={(event) => event.preventDefault()}
                onDrop={() => void link({ table: table.name, column: field.name })}
                onClick={() => void link({ table: table.name, column: field.name })}
              >
                {field.name}
              </button>
            ))}
          </div>
        ))}
      </div>
      <ul>
        {rels.map((rel) => (
          <li key={rel.id ?? `${rel.from?.table}.${rel.from?.column}`}>
            {rel.from?.table}.{rel.from?.column} → {rel.to?.table}.{rel.to?.column}
          </li>
        ))}
      </ul>
    </div>
  );
}
