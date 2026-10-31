/** A workspace's apps: a chosen set of its reports, published to an audience. */
import { useEffect, useState } from "react";

import { parseEmails, sharing, type AppDraft, type MagApp } from "../shared/sharing";
import type { ReportSummary } from "../types/api";
import { apiFetch } from "../shared/api";

const EMPTY: AppDraft = { name: "", description: null, reportIds: [], audience: [], isPublished: false };

export function AppsPanel({ workspaceId }: { workspaceId: string }) {
  const [apps, setApps] = useState<MagApp[]>([]);
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [editing, setEditing] = useState<{ id?: string; draft: AppDraft; audience: string } | null>(null);
  const [error, setError] = useState("");

  function load() {
    sharing.workspaceApps(workspaceId).then(setApps).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Couldn't load apps"));
  }
  useEffect(() => {
    load();
    apiFetch<ReportSummary[]>(`/workspaces/${workspaceId}/reports`).then(setReports).catch(() => undefined);
  }, [workspaceId]);

  async function save() {
    if (!editing) return;
    setError("");
    try {
      await sharing.saveApp(workspaceId, { ...editing.draft, audience: parseEmails(editing.audience) }, editing.id);
      setEditing(null);
      load();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Couldn't save the app");
    }
  }

  async function remove(app: MagApp) {
    if (!window.confirm(`Delete the app “${app.name}”? Its audience loses access to its reports.`)) return;
    try {
      await sharing.deleteApp(workspaceId, app.id);
      load();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Couldn't delete the app");
    }
  }

  function edit(app?: MagApp) {
    setError("");
    setEditing(
      app
        ? { id: app.id, draft: { name: app.name, description: app.description, reportIds: app.reports.map((r) => r.id), audience: app.audience, isPublished: app.isPublished }, audience: app.audience.join("\n") }
        : { draft: { ...EMPTY }, audience: "" },
    );
  }

  const draft = editing?.draft;
  const toggle = (id: string) =>
    editing && setEditing({ ...editing, draft: { ...editing.draft, reportIds: editing.draft.reportIds.includes(id) ? editing.draft.reportIds.filter((item) => item !== id) : [...editing.draft.reportIds, id] } });

  return (
    <div>
      <div className="ws-header">
        <p className="ws-muted">An app gives a set of this workspace's reports to people who aren't members. They see the reports, nothing else.</p>
        <button type="button" className="ws-btn primary" onClick={() => edit()}>+ New app</button>
      </div>
      {error && <p className="ws-error">{error}</p>}
      {apps.length === 0 ? (
        <div className="ws-empty"><p>No apps yet.</p></div>
      ) : (
        <table className="ws-table">
          <thead>
            <tr><th>App</th><th>Reports</th><th>Audience</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {apps.map((app) => (
              <tr key={app.id}>
                <td>{app.name}</td>
                <td className="ws-muted">{app.reports.map((r) => r.name).join(", ") || "—"}</td>
                <td className="ws-muted">{app.audience.length} {app.audience.length === 1 ? "person" : "people"}</td>
                <td>{app.isPublished ? <span className="ws-badge editor">● Published</span> : <span className="ws-badge viewer">○ Draft</span>}</td>
                <td className="notify-actions">
                  <button type="button" className="ws-btn small" onClick={() => edit(app)}>Edit</button>
                  <button type="button" className="ws-btn small" onClick={() => void remove(app)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editing && draft && (
        <div className="modal-backdrop" onClick={() => setEditing(null)}>
          <div className="modal app-dialog" role="dialog" aria-label={editing.id ? "Edit app" : "New app"} onClick={(event) => event.stopPropagation()}>
            <h3>{editing.id ? "Edit app" : "New app"}</h3>
            <label className="app-field">
              <span>Name</span>
              <input className="ws-input" value={draft.name} onChange={(event) => setEditing({ ...editing, draft: { ...draft, name: event.target.value } })} autoFocus />
            </label>
            <label className="app-field">
              <span>Description</span>
              <input className="ws-input" value={draft.description ?? ""} onChange={(event) => setEditing({ ...editing, draft: { ...draft, description: event.target.value || null } })} />
            </label>
            <fieldset className="app-field app-reports">
              <legend>Reports: the app shows them as tabs, in the order you tick them</legend>
              {reports.length === 0 && <p className="ws-muted">This workspace has no reports yet.</p>}
              {reports.map((report) => (
                <label key={report.id} className="app-check">
                  <input type="checkbox" checked={draft.reportIds.includes(report.id)} onChange={() => toggle(report.id)} />
                  {report.name}
                </label>
              ))}
            </fieldset>
            <label className="app-field">
              <span>Audience: one email per line</span>
              <textarea className="ws-input" rows={4} value={editing.audience} placeholder="name@example.com" onChange={(event) => setEditing({ ...editing, audience: event.target.value })} />
            </label>
            <label className="app-check">
              <input type="checkbox" checked={draft.isPublished} onChange={(event) => setEditing({ ...editing, draft: { ...draft, isPublished: event.target.checked } })} />
              Published: the audience can open it
            </label>
            {error && <p className="ws-error">{error}</p>}
            <div className="modal-footer">
              <button type="button" className="ws-btn" onClick={() => setEditing(null)}>Cancel</button>
              <button type="button" className="ws-btn primary" disabled={!draft.name.trim()} onClick={() => void save()}>Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
