import { describe, expect, it } from "vitest";

import { safeNext } from "./LoginPage";

describe("where sign-in goes next", () => {
  it("returns to a page inside MagBI", () => {
    expect(safeNext("/workspaces/abc/reports/def/view")).toBe("/workspaces/abc/reports/def/view");
  });

  it("never follows a link to another site", () => {
    expect(safeNext("https://evil.example/steal")).toBe("/workspaces");
    expect(safeNext("//evil.example")).toBe("/workspaces");
    expect(safeNext("/\\evil.example")).toBe("/workspaces");
    expect(safeNext(null)).toBe("/workspaces");
  });
});
