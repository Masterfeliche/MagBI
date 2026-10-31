/** Apps published to me and reports shared with me, from workspaces I may not belong to. */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { sharing, type MagApp, type SharedReport } from "../shared/sharing";

export function SharedWithMe({ onFound }: { onFound?: (count: number) => void }) {
  const navigate = useNavigate();
  const [apps, setApps] = useState<MagApp[]>([]);
  const [shared, setShared] = useState<SharedReport[]>([]);

  useEffect(() => {
    sharing.myApps().then(setApps).catch(() => undefined);
    sharing.sharedWithMe().then(setShared).catch(() => undefined);
  }, []);

  useEffect(() => onFound?.(apps.length + shared.length), [apps.length, shared.length, onFound]);

  if (apps.length === 0 && shared.length === 0) return null;

  return (
    <>
      {apps.length > 0 && (
        <section className="ws-section">
          <h2>Apps</h2>
          <div className="ws-grid">
            {apps.map((app) => (
              <div key={app.id} className="ws-card" role="link" tabIndex={0}
                onClick={() => navigate(`/apps/${app.id}`)} onKeyDown={(event) => event.key === "Enter" && navigate(`/apps/${app.id}`)}>
                <div className="ws-card-name">{app.name}</div>
                <div className="ws-muted">
                  {app.reports.length} {app.reports.length === 1 ? "report" : "reports"} · {app.workspaceName}
                </div>
                {app.description && <div className="ws-muted">{app.description}</div>}
              </div>
            ))}
          </div>
        </section>
      )}
      {shared.length > 0 && (
        <section className="ws-section">
          <h2>Shared with me</h2>
          <table className="ws-table">
            <thead>
              <tr><th>Report</th><th>Workspace</th><th>Shared by</th></tr>
            </thead>
            <tbody>
              {shared.map((item) => (
                <tr key={item.reportId}>
                  <td>
                    <button type="button" className="ws-link" onClick={() => navigate(`/workspaces/${item.workspaceId}/reports/${item.reportId}/view`)}>
                      {item.reportName}
                    </button>
                  </td>
                  <td className="ws-muted">{item.workspaceName}</td>
                  <td className="ws-muted">{item.sharedBy}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
