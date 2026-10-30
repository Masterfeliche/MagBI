/** Workspace detail page with tabbed sections. */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { apiFetch } from "../shared/api";
import type { Workspace } from "../types/api";
import { ConnectionList } from "./ConnectionList";
import { DatasetList } from "./DatasetList";
import { ReportList } from "./ReportList";

type Tab = "datasets" | "reports" | "connections";

export function WorkspaceDetail() {
  const { workspaceId } = useParams();
  const navigate = useNavigate();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<Tab>("datasets");

  useEffect(() => {
    if (!workspaceId) return;
    apiFetch<Workspace>(`/workspaces/${workspaceId}`)
      .then(setWorkspace)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [workspaceId]);

  if (loading) return <div className="ws-page"><p className="ws-loading">Loading...</p></div>;
  if (error) {
    return (
      <div className="ws-page">
        <p className="ws-error">
          {error} <button type="button" className="ws-btn small" onClick={() => window.location.reload()}>Retry</button>
        </p>
      </div>
    );
  }
  if (!workspace || !workspaceId) return null;

  const tabs: { key: Tab; label: string }[] = [
    { key: "datasets", label: "Datasets" },
    { key: "reports", label: "Reports" },
    { key: "connections", label: "Connections" },
  ];

  return (
    <div className="ws-page">
      <div className="ws-header">
        <div className="ws-breadcrumb">
          <button className="ws-link" onClick={() => navigate("/workspaces")}>Workspaces</button>
          <span className="ws-sep">/</span>
          <h1>{workspace.name}</h1>
        </div>
        <div className="ws-actions">
          <button
            className="ws-btn primary"
            onClick={() => navigate(`/workspaces/${workspaceId}/datasets/new`)}
          >
            + New dataset
          </button>
          <button
            className="ws-btn"
            onClick={() => navigate(`/workspaces/${workspaceId}/connections/new`)}
          >
            + New connection
          </button>
          <button className="ws-btn" onClick={() => navigate(`/workspaces/${workspaceId}/embed`)}>
            Embed
          </button>
        </div>
      </div>

      <div className="ws-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={activeTab === tab.key ? "ws-tab active" : "ws-tab"}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="ws-tab-content">
        {activeTab === "datasets" && <DatasetList workspaceId={workspaceId} />}
        {activeTab === "reports" && <ReportList workspaceId={workspaceId} />}
        {activeTab === "connections" && <ConnectionList workspaceId={workspaceId} />}
      </div>
    </div>
  );
}
