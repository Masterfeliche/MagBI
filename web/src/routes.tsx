import { Navigate, Route, Routes } from "react-router-dom";

import { DesignerPage } from "./designer/DesignerPage";
import { AppShell } from "./workspace/AppShell";
import { ConnectionForm } from "./workspace/ConnectionForm";
import { DatasetWizard } from "./workspace/DatasetWizard";
import { WorkspaceDetail } from "./workspace/WorkspaceDetail";
import { WorkspaceList } from "./workspace/WorkspaceList";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/workspaces" element={<WorkspaceList />} />
        <Route path="/workspaces/:workspaceId" element={<WorkspaceDetail />} />
        <Route path="/workspaces/:workspaceId/connections/new" element={<ConnectionForm />} />
        <Route path="/workspaces/:workspaceId/datasets/new" element={<DatasetWizard />} />
      </Route>
      <Route
        path="/workspaces/:workspaceId/datasets/:datasetId/designer"
        element={<DesignerPage />}
      />
      <Route path="/" element={<Navigate to="/workspaces" replace />} />
    </Routes>
  );
}
