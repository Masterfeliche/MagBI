/** Share one report with people outside the workspace, and stop sharing it. */
import { useEffect, useState } from "react";

import { sharing, type Share } from "../shared/sharing";

export function ShareDialog({ workspaceId, reportId, reportName, onClose }: {
  workspaceId: string;
  reportId: string;
  reportName: string;
  onClose: () => void;
}) {
  const [shares, setShares] = useState<Share[]>([]);
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    sharing.shares(workspaceId, reportId).then(setShares).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Couldn't load who it's shared with"));
  }
  useEffect(load, [workspaceId, reportId]);

  async function add() {
    if (!email.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await sharing.share(workspaceId, reportId, email.trim());
      setEmail("");
      load();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Couldn't share");
    } finally {
      setBusy(false);
    }
  }

  async function remove(share: Share) {
    setError("");
    try {
      await sharing.unshare(workspaceId, reportId, share.userId);
      load();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Couldn't stop sharing");
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal share-dialog" role="dialog" aria-label={`Share ${reportName}`} onClick={(event) => event.stopPropagation()}>
        <h3>Share “{reportName}”</h3>
        <p className="ws-muted">
          People you share with can view this report and nothing else in the workspace. Row-level security still applies to them.
        </p>
        <div className="form-row">
          <input
            className="ws-input"
            type="email"
            placeholder="name@example.com"
            aria-label="Email of the person to share with"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && void add()}
            autoFocus
          />
          <button type="button" className="ws-btn primary" onClick={() => void add()} disabled={busy || !email.trim()}>
            Share
          </button>
        </div>
        {error && <p className="ws-error">{error}</p>}
        {shares.length === 0 ? (
          <p className="ws-muted">Not shared with anyone outside the workspace yet.</p>
        ) : (
          <table className="ws-table">
            <thead>
              <tr><th>Person</th><th>Shared by</th><th></th></tr>
            </thead>
            <tbody>
              {shares.map((share) => (
                <tr key={share.userId}>
                  <td>{share.name && share.name !== share.email ? `${share.name} · ${share.email}` : share.email}</td>
                  <td className="ws-muted">{share.sharedBy}</td>
                  <td><button type="button" className="ws-btn small" onClick={() => void remove(share)}>Stop sharing</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="modal-footer">
          <button type="button" className="ws-btn" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}
