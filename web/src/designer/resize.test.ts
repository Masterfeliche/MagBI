import { describe, expect, it } from "vitest";

import { MIN_HEIGHT, MIN_WIDTH, PAGE_WIDTH, resizeBox } from "./layout";

const start = { x: 100, y: 80, width: 360, height: 240 };

describe("resize", () => {
  it("widens from the right and the left and keeps a minimum size", () => {
    const east = resizeBox(start, "e", 500, 80);
    expect(east).toEqual({ x: 100, y: 80, width: 400, height: 240 });

    const west = resizeBox(start, "w", 80, 80);
    expect(west).toEqual({ x: 80, y: 80, width: 380, height: 240 });

    const tooSmall = resizeBox(start, "w", 450, 80);
    expect(tooSmall.width).toBe(MIN_WIDTH);
    expect(tooSmall.x + tooSmall.width).toBe(start.x + start.width);

    const corner = resizeBox(start, "se", 200, 100);
    expect(corner.width).toBeGreaterThanOrEqual(MIN_WIDTH);
    expect(corner.height).toBe(MIN_HEIGHT);
    expect(corner.x).toBe(100);
    expect(corner.y).toBe(80);

    const pastPage = resizeBox(start, "e", PAGE_WIDTH + 50, 80);
    expect(pastPage.x + pastPage.width).toBe(PAGE_WIDTH);
  });
});
