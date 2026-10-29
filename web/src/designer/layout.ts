/** Page size, 10px snap, and palette placement. Pointers are divided by the CSS scale. */

import type { VisualDefinition } from "../types/report";

export const PAGE_WIDTH = 1760;
export const PAGE_HEIGHT = 990;
export const SNAP = 10;

export function snap(value: number): number {
  return Math.round(value / SNAP) * SNAP;
}

export function pagePoint(
  clientX: number,
  clientY: number,
  originX: number,
  originY: number,
  scale: number,
): { x: number; y: number } {
  const safe = scale === 0 ? 1 : scale;
  return {
    x: snap((clientX - originX) / safe),
    y: snap((clientY - originY) / safe),
  };
}

export function clampPosition(
  x: number,
  y: number,
  width: number,
  height: number,
): { x: number; y: number } {
  return {
    x: Math.min(Math.max(snap(x), 0), Math.max(PAGE_WIDTH - width, 0)),
    y: Math.min(Math.max(snap(y), 0), Math.max(PAGE_HEIGHT - height, 0)),
  };
}

export function blankReport(name: string, datasetId: string) {
  return {
    schemaVersion: "1",
    name,
    datasetId,
    pages: [
      {
        name: "page-1",
        displayName: "Page 1",
        width: PAGE_WIDTH,
        height: PAGE_HEIGHT,
        visuals: [],
        filters: [],
      },
    ],
  };
}

export function placeVisual(
  visuals: Pick<VisualDefinition, "x" | "y" | "width" | "height">[],
  type: string,
  id: string,
): VisualDefinition {
  const width = 360;
  const height = type === "card" ? 140 : 240;
  const slot = nextSlot(visuals, width, height);
  return { id, type, x: slot.x, y: slot.y, width, height, wells: {} };
}

function nextSlot(
  visuals: Pick<VisualDefinition, "x" | "y" | "width" | "height">[],
  width: number,
  height: number,
): { x: number; y: number } {
  for (let y = 0; y + height <= PAGE_HEIGHT; y += SNAP) {
    for (let x = 0; x + width <= PAGE_WIDTH; x += SNAP) {
      const blocked = visuals.some((visual) =>
        overlaps(x, y, width, height, visual.x, visual.y, visual.width, visual.height),
      );
      if (!blocked) return { x, y };
    }
  }
  return { x: 0, y: 0 };
}

function overlaps(
  ax: number,
  ay: number,
  aw: number,
  ah: number,
  bx: number,
  by: number,
  bw: number,
  bh: number,
): boolean {
  return ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by;
}
