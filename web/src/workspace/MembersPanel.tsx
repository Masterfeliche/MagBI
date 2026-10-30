import { useEffect, useState } from "react";

import { apiFetch } from "../shared/api";

interface Member {
  user_id: string;
  email: string;
  name: string;
  role: string;
}

export function MembersPanel({ workspaceId }: { workspaceId: string }) {
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [error, setError] = useState("");

  function load() {
    apiFetch<Member[]>(`/workspaces/${workspaceId}/members`)
      .then(setMembers)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load members"));
  }

  useEffect(load, [workspaceId]);

  async function invite() {
    setError("");
    try {
      await apiFetch(`/workspaces/${workspaceId}/members`, {
        method: "POST",
        body: JSON.stringify({ email, role }),
      });
      setEmail("");
      load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not invite");
    }
  }

  return (
    <div>
      {error && <p className="ws-error">{error}</p>}
      <div className="form-row">
        <input className="ws-input" value={email} placeholder="user@example.com" onChange={(event) => setEmail(event.target.value)} />
        <select className="ws-input" value={role} onChange={(event) => setRole(event.target.value)}>
          <option value="viewer">Viewer</option>
          <option value="editor">Editor</option>
          <option value="admin">Admin</option>
        </select>
        <button type="button" className="ws-btn primary" onClick={() => void invite()}>Invite</button>
      </div>
      <table className="ws-table">
        <thead>
          <tr><th>Name</th><th>Email</th><th>Role</th></tr>
        </thead>
        <tbody>
          {members.map((member) => (
            <tr key={member.user_id}>
              <td>{member.name}</td>
              <td>{member.email}</td>
              <td>{member.role}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
