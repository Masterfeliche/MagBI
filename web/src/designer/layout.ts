/** Page size, 10px snap, and palette placement. Pointers are divided by the CSS scale. */

import type { VisualDefinition } from "../types/report";

export const PAGE_WIDTH = 1760;
export const PAGE_HEIGHT = 990;
export const SNAP = 10;
export const MIN_WIDTH = 80;
export const MIN_HEIGHT = 60;

export type ResizeHandle = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function snap(value: number): number {
  return Math.round(value / SNAP) * SNAP;
}

export function pageOffset(
  clientX: number,
  clientY: number,
  originX: number,
  originY: number,
  scale: number,
): { x: number; y: number } {
  const safe = scale === 0 ? 1 : scale;
  return { x: (clientX - originX) / safe, y: (clientY - originY) / safe };
}

export function pagePoint(
  clientX: number,
  clientY: number,
  originX: number,
  originY: number,
  scale: number,
): { x: number; y: number } {
  const point = pageOffset(clientX, clientY, originX, originY, scale);
  return { x: snap(point.x), y: snap(point.y) };
}

/** Move one or two edges. The opposite edge stays put. The box stays on the page (desktop unless given). */
export function resizeBox(
  start: Box,
  handle: ResizeHandle,
  pointerX: number,
  pointerY: number,
  resolve: (value: number, axis: "x" | "y") => number = (value) => snap(value),
  page: { width: number; height: number } = { width: PAGE_WIDTH, height: PAGE_HEIGHT },
): Box {
  let left = start.x;
  let right = start.x + start.width;
  let top = start.y;
  let bottom = start.y + start.height;
  if (handle.includes("w")) left = resolve(pointerX, "x");
  if (handle.includes("e")) right = resolve(pointerX, "x");
  if (handle.includes("n")) top = resolve(pointerY, "y");
  if (handle.includes("s")) bottom = resolve(pointerY, "y");
  if (right - left < MIN_WIDTH) {
    if (handle.includes("w")) left = right - MIN_WIDTH;
    else right = left + MIN_WIDTH;
  }
  if (bottom - top < MIN_HEIGHT) {
    if (handle.includes("n")) top = bottom - MIN_HEIGHT;
    else bottom = top + MIN_HEIGHT;
  }
  if (left < 0) left = 0;
  if (top < 0) top = 0;
  if (right > page.width) right = page.width;
  if (bottom > page.height) bottom = page.height;
  if (right - left < MIN_WIDTH) {
    if (handle.includes("w")) left = Math.max(0, right - MIN_WIDTH);
    else right = Math.min(page.width, left + MIN_WIDTH);
  }
  if (bottom - top < MIN_HEIGHT) {
    if (handle.includes("n")) top = Math.max(0, bottom - MIN_HEIGHT);
    else bottom = Math.min(page.height, top + MIN_HEIGHT);
  }
  return { x: left, y: top, width: right - left, height: bottom - top };
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
  const height = type === "card" ? 180 : 240;
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
