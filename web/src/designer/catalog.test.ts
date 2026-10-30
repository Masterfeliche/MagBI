import { describe, expect, it } from "vitest";

import { VISUALS } from "./catalog";

describe("visual catalog", () => {
  it("gives each of the 13 types a distinct icon path", () => {
    expect(VISUALS.length).toBeGreaterThanOrEqual(13);
    const paths = VISUALS.map((visual) => visual.icon);
    expect(paths.every((path) => path.length > 10)).toBe(true);
    expect(new Set(paths).size).toBe(VISUALS.length);
  });
});
