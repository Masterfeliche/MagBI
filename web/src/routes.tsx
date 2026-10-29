import { Route, Routes } from "react-router-dom";

import { DesignerPage } from "./designer/DesignerPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<div>MagBI</div>} />
      <Route
        path="/workspaces/:workspaceId/datasets/:datasetId/designer"
        element={<DesignerPage />}
      />
    </Routes>
  );
}
