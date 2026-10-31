/** Measure editor: name, home table, and the DAX expression, with the supported functions to hand. */

import Editor, { type OnMount } from "@monaco-editor/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { adaptDataset, type DesignerTable } from "../designer/model";
import { apiFetch } from "../shared/api";
import { insertText, loadDaxFunctions, searchFunctions, type DaxFunction } from "./daxFunctions";

type MonacoEditor = Parameters<OnMount>[0];
type Monaco = Parameters<OnMount>[1];
type MonacoModel = ReturnType<MonacoEditor["getModel"]> & object;
type MonacoPosition = NonNullable<ReturnType<MonacoEditor["getPosition"]>>;
let completionsRegistered = false;

/** Autocomplete for every supported function, registered once for the "dax" language. */
function registerCompletions(monaco: Monaco, functions: () => DaxFunction[]) {
  if (completionsRegistered) return;
  completionsRegistered = true;
  monaco.languages.register({ id: "dax" });
  monaco.languages.registerCompletionItemProvider("dax", {
    provideCompletionItems: (model: MonacoModel, position: MonacoPosition) => {
      const word = model.getWordUntilPosition(position);
      const range = { startLineNumber: position.lineNumber, endLineNumber: position.lineNumber, startColumn: word.startColumn, endColumn: word.endColumn };
      return {
        suggestions: functions().map((item) => ({
          label: item.name,
          kind: monaco.languages.CompletionItemKind.Function,
          detail: item.signature,
          documentation: item.description,
          insertText: insertText(item),
          range,
        })),
      };
    },
  });
}
import "../workspace/workspace.css";

export function MeasureEditor({
  workspaceId,
  datasetId,
  modelVersion,
  tables,
  onClose,
  onSaved,
}: {
  workspaceId: string;
  datasetId: string;
  modelVersion: number;
  tables: DesignerTable[];
  onClose: () => void;
  onSaved: (tables: DesignerTable[], modelVersion: number) => void;
}) {
  const [name, setName] = useState("New Measure");
  const [table, setTable] = useState(tables[0]?.name ?? "");
  const [expression, setExpression] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [functions, setFunctions] = useState<DaxFunction[]>([]);
  const [search, setSearch] = useState("");
  const editor = useRef<MonacoEditor | null>(null);
  const known = useRef<DaxFunction[]>([]);
  const shown = useMemo(() => searchFunctions(functions, search), [functions, search]);

  useEffect(() => {
    void loadDaxFunctions().then((list) => {
      known.current = list;
      setFunctions(list);
    });
  }, []);

  function insert(item: DaxFunction) {
    const current = editor.current;
    if (!current) {
      setExpression((value) => value + insertText(item));
      return;
    }
    const selection = current.getSelection();
    if (selection) current.executeEdits("function-list", [{ range: selection, text: insertText(item), forceMoveMarkers: true }]);
    current.focus();
  }

  async function save() {
    if (!table || !name.trim() || !expression.trim()) {
      setError("Name, table, and expression are required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const body = await apiFetch<{ model_version: number; definition: unknown }>(
        `/workspaces/${workspaceId}/datasets/${datasetId}/definition/measures`,
        {
          method: "POST",
          body: JSON.stringify({
            model_version: modelVersion,
            table,
            measure: { name: name.trim(), expression: expression.trim() },
          }),
        },
      );
      onSaved(adaptDataset(body.definition), body.model_version);
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not save measure");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal measure-editor" onClick={(event) => event.stopPropagation()}>
        <h3>New measure</h3>
        {error && <p className="ws-error">{error}</p>}
        <div className="form-row">
          <label htmlFor="measure-name">Name</label>
          <input
            id="measure-name"
            className="ws-input"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <div className="form-row">
          <label htmlFor="measure-table">Table</label>
          <select
            id="measure-table"
            className="ws-input"
            value={table}
            onChange={(event) => setTable(event.target.value)}
          >
            {tables.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        <div className="form-row">
          <label htmlFor="measure-dax">DAX</label>
          <div className="measure-dax">
            <Editor
              height="180px"
              defaultLanguage="dax"
              value={expression}
              onChange={(value) => setExpression(value ?? "")}
              onMount={(instance, monaco) => {
                editor.current = instance;
                registerCompletions(monaco, () => known.current);
              }}
              options={{ minimap: { enabled: false }, fontSize: 13, wordWrap: "on" }}
            />
          </div>
        </div>
        <div className="form-row">
          <label htmlFor="measure-functions">Functions</label>
          <div className="dax-functions">
            <input
              id="measure-functions"
              className="ws-input"
              value={search}
              placeholder={`Search ${functions.length} functions`}
              onChange={(event) => setSearch(event.target.value)}
            />
            <ul>
              {shown.map((item) => (
                <li key={item.name}>
                  <button type="button" onClick={() => insert(item)} title={`Insert ${item.name}`}>
                    <code>{item.signature}</code>
                    <span>{item.description}</span>
                  </button>
                </li>
              ))}
              {shown.length === 0 && <li className="ws-hint">No function matches "{search}".</li>}
            </ul>
          </div>
        </div>
        <div className="form-actions">
          <button type="button" className="ws-btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="ws-btn primary" disabled={saving} onClick={() => void save()}>
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
