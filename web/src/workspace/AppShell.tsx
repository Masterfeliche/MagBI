import { Link, Outlet, useParams } from "react-router-dom";
import "./workspace.css";

export function AppShell() {
  const { workspaceId } = useParams();

  return (
    <div className="app-shell">
      <div className="app-topbar">
        <Link to="/workspaces" className="app-topbar-logo">MagBI</Link>
        <nav className="app-breadcrumb">
          {workspaceId && (
            <>
              <span className="app-breadcrumb-sep">/</span>
              <Link to={`/workspaces/${workspaceId}`}>Workspace</Link>
            </>
          )}
        </nav>
      </div>
      <div className="app-content">
        <Outlet />
      </div>
    </div>
  );
}
