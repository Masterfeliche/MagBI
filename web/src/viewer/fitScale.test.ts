import { describe, expect, it } from "vitest";

import { PAGE_HEIGHT, PAGE_WIDTH } from "../designer/layout";
import { fitScale } from "./fitScale";

describe("fitScale", () => {
  it("fits to width or to the full page", () => {
    expect(fitScale("width", PAGE_WIDTH / 2, 10)).toBe(0.5);
    expect(fitScale("page", PAGE_WIDTH, PAGE_HEIGHT / 2)).toBe(0.5);
  });
});
