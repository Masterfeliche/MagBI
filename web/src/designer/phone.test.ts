import { describe, expect, it } from "vitest";

import type { PageDefinition, VisualDefinition } from "../types/report";
import { blankReport, resizeBox } from "./layout";
import {
  autoPhoneLayout,
  clampPhoneBox,
  hasPhoneLayout,
  PHONE_MAX_HEIGHT,
  PHONE_MIN_HEIGHT,
  PHONE_WIDTH,
  phoneHeight,
  placeOnPhone,
  unplacedVisuals,
} from "./phone";
import { useDesignerStore } from "./store";

function visual(id: string, type: string, x: number, y: number, width: number, height: number, hidden = false): VisualDefinition {
  return { id, type, x, y, width, height, wells: {}, ...(hidden ? { properties: { hidden: true } } : {}) };
}

// The Stock Accuracy arrangement: a filter column on the left, the chain and charts on the right.
const page: PageDefinition = {
  name: "p",
  displayName: "P",
  width: 1760,
  height: 990,
  visuals: [
    visual("header", "header", 28, 14, 1704, 88),
    visual("frame", "frame", 28, 104, 340, 862),
    visual("filters-label", "label", 40, 112, 316, 22),
    visual("warehouse", "slicer", 40, 138, 316, 52),
    visual("count", "slicer", 40, 198, 316, 52),
    visual("chain", "chain", 398, 111, 1320, 52),
    visual("figures-label", "label", 40, 268, 316, 22),
    visual("kpi-1", "kpi", 40, 294, 316, 124),
    visual("kpi-2", "kpi", 40, 428, 316, 124),
    visual("meter", "meter", 384, 186, 320, 250),
    visual("grid", "grid", 384, 718, 1348, 248),
    visual("bars", "bars", 384, 452, 860, 250),
    visual("gone", "bars", 0, 0, 100, 100, true),
  ],
};

describe("phone layout", () => {
  it("stacks the page in phone reading order, pairs slicers and leaves frames and hidden visuals off", () => {
    const layout = autoPhoneLayout(page);
    expect(layout.visuals.map((item) => item.id)).toEqual([
      "header", "filters-label", "warehouse", "count", "chain", "figures-label", "kpi-1", "kpi-2", "meter", "bars", "grid",
    ]);
    const at = new Map(layout.visuals.map((item) => [item.id, item]));
    expect(at.get("warehouse")?.y).toBe(at.get("count")?.y);
    expect((at.get("warehouse")?.width ?? 0) + (at.get("count")?.width ?? 0)).toBeLessThan(PHONE_WIDTH);
    for (const item of layout.visuals) {
      expect(item.x).toBeGreaterThanOrEqual(0);
      expect(item.x + item.width).toBeLessThanOrEqual(PHONE_WIDTH);
    }
    // No two placed visuals overlap.
    for (const a of layout.visuals) {
      for (const b of layout.visuals) {
        if (a === b) continue;
        const overlap = a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
        expect(overlap, `${a.id} overlaps ${b.id}`).toBe(false);
      }
    }
  });

  it("lists what isn't placed yet and adds a visual full width under the rest", () => {
    expect(hasPhoneLayout(page)).toBe(false);
    expect(unplacedVisuals(page)).toHaveLength(12);
    const one = placeOnPhone(undefined, page.visuals[0] as VisualDefinition);
    const two = placeOnPhone(one, page.visuals[7] as VisualDefinition);
    expect(two.visuals[1]).toMatchObject({ id: "kpi-1", x: 10, width: 340, y: 10 + 200 + 10 });
    const placed = { ...page, phone: two };
    expect(hasPhoneLayout(placed)).toBe(true);
    expect(unplacedVisuals(placed).map((item) => item.id)).not.toContain("kpi-1");
    expect(phoneHeight(two)).toBe(PHONE_MIN_HEIGHT);
    expect(phoneHeight({ visuals: [{ id: "a", x: 0, y: 900, width: 100, height: 100 }] })).toBe(1010);
  });

  it("keeps boxes on the narrow canvas", () => {
    expect(clampPhoneBox({ x: 300, y: -20, width: 200, height: 100 })).toEqual({ x: 160, y: 0, width: 200, height: 100 });
    expect(resizeBox({ x: 10, y: 10, width: 300, height: 100 }, "e", 900, 0, undefined, { width: PHONE_WIDTH, height: PHONE_MAX_HEIGHT }).width).toBe(350);
    expect(resizeBox({ x: 10, y: 1500, width: 300, height: 100 }, "s", 0, 2000, undefined, { width: PHONE_WIDTH, height: PHONE_MAX_HEIGHT }).height).toBe(500);
  });
});

describe("phone layout in the designer store", () => {
  it("places, moves, removes and auto-arranges with undo, and a deleted visual leaves the phone too", () => {
    const store = useDesignerStore.getState;
    store().replaceReport(blankReport("Board", "ds"));
    store().addVisual("card");
    store().addVisual("column");
    const [card, column] = store().report.pages[0]?.visuals.map((item) => item.id) ?? [];
    store().addToPhone(card ?? "");
    expect(store().report.pages[0]?.phone?.visuals).toHaveLength(1);
    store().setPhoneBox(card ?? "", { x: 500, y: 40, width: 200, height: 120 });
    expect(store().report.pages[0]?.phone?.visuals[0]).toEqual({ id: card, x: 160, y: 40, width: 200, height: 120 });
    // The desktop position is untouched.
    expect(store().report.pages[0]?.visuals[0]).toMatchObject({ x: 0, y: 0 });
    store().undo();
    expect(store().report.pages[0]?.phone?.visuals[0]?.y).toBe(10);
    store().redo();
    expect(store().report.pages[0]?.phone?.visuals[0]?.y).toBe(40);

    store().autoArrangePhone();
    expect(store().report.pages[0]?.phone?.visuals.map((item) => item.id)).toEqual([card, column]);
    store().removeFromPhone(column ?? "");
    expect(store().report.pages[0]?.visuals).toHaveLength(2);
    expect(store().report.pages[0]?.phone?.visuals.map((item) => item.id)).toEqual([card]);
    store().removeVisual(card ?? "");
    expect(store().report.pages[0]?.phone).toBeUndefined();
    store().undo();
    expect(store().report.pages[0]?.phone?.visuals.map((item) => item.id)).toEqual([card]);
    store().clearPhoneLayout();
    expect("phone" in (store().report.pages[0] ?? {})).toBe(false);
  });
});
