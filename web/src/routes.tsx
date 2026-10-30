import { Navigate, Route, Routes } from "react-router-dom";

import { DesignerPage } from "./designer/DesignerPage";
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
      <Route element={<AppShell />}>
        <Route path="/workspaces" element={<WorkspaceList />} />
        <Route path="/workspaces/:workspaceId" element={<WorkspaceDetail />} />
        <Route path="/workspaces/:workspaceId/connections/new" element={<ConnectionForm />} />
        <Route path="/workspaces/:workspaceId/datasets/new" element={<DatasetWizard />} />
        <Route path="/workspaces/:workspaceId/embed" element={<EmbedPage />} />
      </Route>
      <Route
        path="/workspaces/:workspaceId/datasets/:datasetId/designer"
        element={<DesignerPage />}
      />
      <Route
        path="/workspaces/:workspaceId/reports/:reportId/view"
        element={<ReportViewer />}
      />
      <Route path="/" element={<Navigate to="/workspaces" replace />} />
    </Routes>
  );
}
