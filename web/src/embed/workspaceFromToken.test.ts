import { describe, expect, it } from "vitest";

import { workspaceFromToken } from "./workspaceFromToken";

function tokenWith(payload: object): string {
  const body = btoa(JSON.stringify(payload)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `hdr.${body}.sig`;
}

describe("workspaceFromToken", () => {
  it("reads workspaceId from the JWT payload", () => {
    expect(workspaceFromToken(tokenWith({ workspaceId: "ws-1" }))).toBe("ws-1");
    expect(workspaceFromToken("not-a-jwt")).toBeNull();
  });
});
