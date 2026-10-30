/** Chrome-free embed host at /embed/:reportId?token=. */

import { useParams, useSearchParams } from "react-router-dom";

import { ReportViewer } from "../viewer/ReportViewer";
import { workspaceFromToken } from "./workspaceFromToken";

export function EmbedHost() {
  const { reportId } = useParams();
  const [search] = useSearchParams();
  const token = search.get("token") ?? "";
  const workspaceId = workspaceFromToken(token);
  if (!token || !workspaceId || !reportId) {
    return <p className="ws-error">An embed token is required.</p>;
  }
  return <ReportViewer chrome={false} workspaceId={workspaceId} reportId={reportId} />;
}
