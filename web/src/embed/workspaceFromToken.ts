/** Read workspaceId from an embed JWT without verifying the signature. */

export function workspaceFromToken(token: string): string | null {
  const parts = token.split(".");
  if (parts.length < 2) return null;
  try {
    const json = atob(parts[1].replace(/-/g, "+").replace(/_/g, "/"));
    const payload = JSON.parse(json) as { workspaceId?: unknown };
    return typeof payload.workspaceId === "string" && payload.workspaceId
      ? payload.workspaceId
      : null;
  } catch {
    return null;
  }
}
