import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { hasSession } from "./session";

/** App pages need a signed-in user; anyone else goes to sign-in and comes back after. */
export function RequireSession({ children }: { children: ReactNode }) {
  const location = useLocation();
  if (!hasSession()) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <>{children}</>;
}
