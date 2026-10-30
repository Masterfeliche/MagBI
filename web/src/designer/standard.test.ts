import { describe, expect, it } from "vitest";

import { ERP_NATIVE, formatDate, isNoDataLabel, layoutIssues, statusOf } from "./standard";

describe("dashboard standard", () => {
  it("formats dates, maps status, greys no-data, and rejects overlap", () => {
    expect(formatDate("2026-11-03")).toBe("03 Nov 2026");
    expect(formatDate("2026-12-01", "Mon yy")).toBe("Dec 26");
    expect(statusOf("watch").glyph).toBe("◆");
    expect(statusOf("good").word).toBe("On track");
    expect(isNoDataLabel("Not recorded")).toBe(true);
    expect(ERP_NATIVE.data[0]).toBe("#3F6FB0");
    expect(layoutIssues([{ x: 0, y: 0, width: 100, height: 100 }, { x: 50, y: 50, width: 100, height: 100 }])).toHaveLength(1);
    expect(layoutIssues([{ x: 0, y: 0, width: 1760, height: 990 }])).toEqual([]);
  });
});