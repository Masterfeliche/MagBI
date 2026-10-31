import { Link, Outlet, useNavigate, useParams } from "react-router-dom";

import { clearToken, hasSession } from "../shared/session";
import "./workspace.css";

export function AppShell() {
  const { workspaceId } = useParams();
  const navigate = useNavigate();

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
        {hasSession() && (
          <button
            type="button"
            className="app-topbar-signout"
            onClick={() => {
              clearToken();
              navigate("/login", { replace: true });
            }}
          >
            Sign out
          </button>
        )}
      </div>
      <div className="app-content">
        <Outlet />
      </div>
    </div>
  );
}
