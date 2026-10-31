import { describe, expect, it } from "vitest";

import { categoryAxisLabel, chartColors, formatNumber, markLines, titleFrom, trendValues, unitsFormatter } from "./formatChart";

describe("format chart", () => {
  it("hides an empty title, formats thousands, and draws an average line", () => {
    expect(titleFrom({ titleShow: false, title: "Revenue" })).toBeUndefined();
    expect(titleFrom({ title: "Revenue", titleAlign: "Center" })).toMatchObject({ text: "Revenue", left: "center" });
    expect(unitsFormatter("K")?.(2500)).toBe("2.5K");
    expect(markLines([10, 30], { analytics_average: true })).toEqual([{ yAxis: 20, name: "Average" }]);
    expect(chartColors({ color: "#112233" }, ["#aaaaaa", "#bbbbbb"])[0]).toBe("#112233");
    expect(trendValues([2, 4, 6])).toEqual([2, 4, 6]);
    expect(formatNumber(1210240.4699999997)).toBe("1,210,240.47");
    expect(formatNumber(40365.7469999999)).toBe("40,365.75");
    expect(formatNumber(40000, { units: "auto", decimals: 0 })).toBe("40K");
    expect(categoryAxisLabel(30, { show: true, fontSize: 10, color: "#64748B" }).rotate).toBe(45);
    expect(categoryAxisLabel(6, { show: true, fontSize: 10, color: "#64748B" }).rotate).toBe(0);
  });
});

describe("measure format strings", () => {
  it("shows a card value the way its measure's format says", async () => {
    const { formatMeasure } = await import("./formatChart");
    expect(formatMeasure("26244.00", "#,0")).toBe("26,244");
    expect(formatMeasure(312.456, "#,0.0")).toBe("312.5");
    expect(formatMeasure(0.993, "0.0%")).toBe("99.3%");
    expect(formatMeasure(0.5, "0%")).toBe("50%");
    expect(formatMeasure(1234.5, null)).toBe("1,234.50");
  });
});
