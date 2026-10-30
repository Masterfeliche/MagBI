import { describe, expect, it } from "vitest";

import { pickReport } from "./pickReport";

const reports = [
  { id: "old", dataset_id: "ds" },
  { id: "summary", dataset_id: "ds" },
];

describe("pickReport", () => {
  it("opens the requested report instead of the first one for the dataset", () => {
    expect(pickReport(reports, "ds", "summary")?.id).toBe("summary");
    expect(pickReport(reports, "ds", null)?.id).toBe("old");
    expect(pickReport(reports, "ds", "missing")?.id).toBe("old");
  });
});
