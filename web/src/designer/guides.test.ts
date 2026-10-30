import { describe, expect, it } from "vitest";

import { moveWithGuides, snapAxis } from "./guides";

describe("alignment guides", () => {
  it("snaps within 4px of an edge or the page margin and keeps the 10px grid otherwise", () => {
    const other = { x: 0, y: 0, width: 100, height: 100 };
    const aligned = moveWithGuides({ x: 96, y: 200, width: 100, height: 80 }, [other]);
    expect(aligned.box.x).toBe(100);
    expect(aligned.guides).toContainEqual({ axis: "x", at: 100 });

    const grid = moveWithGuides({ x: 90, y: 200, width: 100, height: 80 }, [other]);
    expect(grid.box.x).toBe(90);
    expect(grid.guides.filter((guide) => guide.axis === "x")).toEqual([]);

    const margin = moveWithGuides({ x: 18, y: 40, width: 100, height: 80 }, []);
    expect(margin.box.x).toBe(20);
    expect(margin.guides).toContainEqual({ axis: "x", at: 20 });

    expect(snapAxis(202, [200, 300])).toEqual({ value: 200, guide: 200 });
    expect(snapAxis(214, [200])).toEqual({ value: 210, guide: null });
  });
});
