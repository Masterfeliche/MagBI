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

  it("places five cards in a row then wraps without overlap", () => {
    const cards: ReturnType<typeof placeVisual>[] = [];
    for (let i = 0; i < 5; i += 1) {
      cards.push(placeVisual(cards, "card", String(i)));
    }
    expect(cards.map((card) => ({ x: card.x, y: card.y }))).toEqual([
      { x: 0, y: 0 },
      { x: 360, y: 0 },
      { x: 720, y: 0 },
      { x: 1080, y: 0 },
      { x: 0, y: 180 },
    ]);
    for (let i = 0; i < cards.length; i += 1) {
      for (let j = i + 1; j < cards.length; j += 1) {
        const a = cards[i];
        const b = cards[j];
        const hit = a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
        expect(hit).toBe(false);
      }
    }
  });
});

