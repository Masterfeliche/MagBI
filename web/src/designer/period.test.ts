import { describe, expect, it } from "vitest";

import { arrangeMonths } from "./period";
import { formatNumber } from "./formatChart";

describe("month axis", () => {
  it("sorts by year and fills the empty months with zero", () => {
    const arranged = arrangeMonths(
      ["Jan 28", "Dec 26", "Mar 27", "Oct 27"],
      [{ name: "Batches", values: [10, 118, 46, 10] }],
    );
    expect(arranged?.categories.slice(0, 4)).toEqual(["Dec 26", "Jan 27", "Feb 27", "Mar 27"]);
    expect(arranged?.categories).toContain("Apr 27");
    expect(arranged?.categories.at(-1)).toBe("Jan 28");
    const values = arranged?.series[0]?.values ?? [];
    const apr = arranged?.categories.indexOf("Apr 27") ?? -1;
    expect(values[arranged?.categories.indexOf("Dec 26") ?? -1]).toBe(118);
    expect(values[apr]).toBe(0);
    expect(values.at(-1)).toBe(10);
  });
});

describe("whole numbers", () => {
  it("drops the decimals on a count", () => {
    expect(formatNumber(1724, { whole: true })).toBe("1,724");
    expect(formatNumber(1973281.93)).toBe("1,973,281.93");
  });
});
