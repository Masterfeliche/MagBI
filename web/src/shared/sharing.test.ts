import { describe, expect, it } from "vitest";

import type { ReportDefinition } from "../types/report";
import { alertableVisuals, parseEmails, scheduleLabel } from "./sharing";

const total = { table: "Sales", measure: "Total" };

function report(): ReportDefinition {
  return {
    schemaVersion: "1.0",
    name: "r",
    datasetId: "d",
    pages: [
      {
        name: "p1", displayName: "Overview", width: 1760, height: 990, visuals: [
          { id: "a", type: "card", x: 0, y: 0, width: 1, height: 1, wells: { "y-axis": [total] }, properties: { title: "Sales total" } },
          { id: "b", type: "kpi", x: 0, y: 0, width: 1, height: 1, wells: { "y-axis": [total] } },
          { id: "c", type: "card", x: 0, y: 0, width: 1, height: 1, wells: {} },
          { id: "d", type: "clusteredColumn", x: 0, y: 0, width: 1, height: 1, wells: { "y-axis": [total] } },
        ],
      },
      {
        name: "p2", displayName: "Detail", width: 1760, height: 990, visuals: [
          { id: "e", type: "gauge", x: 0, y: 0, width: 1, height: 1, wells: { "y-axis": [{ table: "Sales", column: "Amount", aggregation: "sum" }] } },
        ],
      },
    ],
  };
}

describe("alertableVisuals", () => {
  it("lists cards, KPI cards and gauges that have a value, named by title or field", () => {
    expect(alertableVisuals(report())).toEqual([
      { id: "a", title: "Sales total", page: "Overview" },
      { id: "b", title: "Total", page: "Overview" },
      { id: "e", title: "Amount", page: "Detail" },
    ]);
  });
});

describe("parseEmails", () => {
  it("splits on lines, commas and spaces, lower-cases and drops repeats", () => {
    expect(parseEmails("Ada@Example.com\nbo@example.com, ada@example.com;  cy@example.com ")).toEqual([
      "ada@example.com",
      "bo@example.com",
      "cy@example.com",
    ]);
    expect(parseEmails("  \n ")).toEqual([]);
  });
});

describe("scheduleLabel", () => {
  it("names the offered schedules and shows any other cron as written", () => {
    expect(scheduleLabel("0 7 * * 1-5")).toBe("Weekdays at 07:00");
    expect(scheduleLabel("30 6 * * 2")).toBe("30 6 * * 2");
  });
});
