/** An app as its audience sees it: its reports as tabs, one open at a time. */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { sharing, type MagApp } from "../shared/sharing";
import { ReportViewer } from "./ReportViewer";

export function AppView() {
  const { appId } = useParams();
  const [app, setApp] = useState<MagApp | null>(null);
  const [current, setCurrent] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!appId) return;
    sharing
      .app(appId)
      .then((body) => {
        setApp(body);
        setCurrent(body.reports[0]?.id ?? "");
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Couldn't open the app"));
  }, [appId]);

  if (error) return <p className="ws-error">{error}</p>;
  if (!app) return <p className="ws-loading">Loading app...</p>;

  return (
    <div className="app-view">
      <header className="app-view-bar">
        <Link to="/workspaces" className="app-topbar-logo">MagBI</Link>
        <strong>{app.name}</strong>
        <nav className="app-view-tabs" aria-label="Reports in this app">
          {app.reports.map((report) => (
            <button key={report.id} type="button" className={report.id === current ? "app-view-tab active" : "app-view-tab"}
              aria-current={report.id === current ? "page" : undefined} onClick={() => setCurrent(report.id)}>
              {report.name}
            </button>
          ))}
        </nav>
      </header>
      {current ? (
        <div className="app-view-report">
          <ReportViewer key={current} workspaceId={app.workspaceId} reportId={current} />
        </div>
      ) : (
        <p className="ws-muted app-view-empty">This app has no reports yet.</p>
      )}
    </div>
  );
}
