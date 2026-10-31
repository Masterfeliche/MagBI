import { Navigate, Route, Routes } from "react-router-dom";

import { DesignerPage } from "./designer/DesignerPage";
import { EmbedHost } from "./embed/EmbedHost";
import { ModelView } from "./model-editor/ModelView";
import { RequireSession } from "./shared/RequireSession";
import { LandingPage } from "./site/LandingPage";
import { LoginPage } from "./site/LoginPage";
import { AppView } from "./viewer/AppView";
import { ReportViewer } from "./viewer/ReportViewer";
import { AppShell } from "./workspace/AppShell";
import { ConnectionForm } from "./workspace/ConnectionForm";
import { DatasetWizard } from "./workspace/DatasetWizard";
import { WorkspaceDetail } from "./workspace/WorkspaceDetail";
import { WorkspaceList } from "./workspace/WorkspaceList";
import { EmbedPage } from "./workspace/EmbedPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<RequireSession><AppShell /></RequireSession>}>
        <Route path="/workspaces" element={<WorkspaceList />} />
        <Route path="/workspaces/:workspaceId" element={<WorkspaceDetail />} />
        <Route path="/workspaces/:workspaceId/connections/new" element={<ConnectionForm />} />
        <Route path="/workspaces/:workspaceId/datasets/new" element={<DatasetWizard />} />
        <Route path="/workspaces/:workspaceId/embed" element={<EmbedPage />} />
      </Route>
      <Route
        path="/workspaces/:workspaceId/datasets/:datasetId/designer"
        element={<RequireSession><DesignerPage /></RequireSession>}
      />
      <Route
        path="/workspaces/:workspaceId/datasets/:datasetId/model"
        element={<RequireSession><ModelView /></RequireSession>}
      />
      <Route
        path="/workspaces/:workspaceId/reports/:reportId/view"
        element={<RequireSession><ReportViewer /></RequireSession>}
      />
      <Route path="/apps/:appId" element={<RequireSession><AppView /></RequireSession>} />
      <Route path="/embed/:reportId" element={<EmbedHost />} />
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
