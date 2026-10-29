import { describe, expect, it } from "vitest";

import { PAGE_HEIGHT, PAGE_WIDTH, pagePoint, placeVisual, snap } from "./layout";

describe("canvas snap", () => {
  it("snaps a pointer through the current scale and places the next visual on the grid", () => {
    expect(snap(14)).toBe(10);
    expect(snap(15)).toBe(20);
    expect(pagePoint(100, 50, 0, 0, 0.5)).toEqual({ x: 200, y: 100 });

    const first = placeVisual([], "column", "a");
    expect(first.x).toBe(0);
    expect(first.y).toBe(0);
    expect(first.x % 10).toBe(0);
    expect(first.width).toBe(360);
    expect(first.height).toBe(240);

    const second = placeVisual([first], "bar", "b");
    expect(second.x).toBe(360);
    expect(second.y).toBe(0);
    expect(PAGE_WIDTH).toBe(1760);
    expect(PAGE_HEIGHT).toBe(990);
  });
});
