/** Snap to a nearby edge, center, or page margin and report the line to draw. */

import { PAGE_HEIGHT, PAGE_WIDTH, snap, type Box } from "./layout";

export const GUIDE_MARGIN = 20;
export const GUIDE_REACH = 4;

export interface Guide {
  axis: "x" | "y";
  at: number;
}

export function moveWithGuides(
  desired: Box,
  others: Box[],
  page: { width: number; height: number } = { width: PAGE_WIDTH, height: PAGE_HEIGHT },
): { box: Box; guides: Guide[] } {
  const x = shift(desired.x, desired.width, "x", others, page.width);
  const y = shift(desired.y, desired.height, "y", others, page.height);
  const box = {
    x: clamp(x.value, 0, page.width - desired.width),
    y: clamp(y.value, 0, page.height - desired.height),
    width: desired.width,
    height: desired.height,
  };
  return {
    box,
    guides: [
      ...(x.guide !== null && box.x === x.value ? [{ axis: "x" as const, at: x.guide }] : []),
      ...(y.guide !== null && box.y === y.value ? [{ axis: "y" as const, at: y.guide }] : []),
    ],
  };
}

export function snapAxis(value: number, targets: number[]): { value: number; guide: number | null } {
  let best: { dist: number; at: number } | null = null;
  for (const at of targets) {
    const dist = Math.abs(value - at);
    if (dist <= GUIDE_REACH && (best === null || dist < best.dist)) best = { dist, at };
  }
  if (best) return { value: best.at, guide: best.at };
  return { value: snap(value), guide: null };
}

export function axisTargets(others: Box[], axis: "x" | "y", page: number): number[] {
  const targets = [GUIDE_MARGIN, page - GUIDE_MARGIN];
  for (const other of others) targets.push(...anchors(other, axis));
  return targets;
}

function shift(
  origin: number,
  size: number,
  axis: "x" | "y",
  others: Box[],
  page: number,
): { value: number; guide: number | null } {
  const targets = axisTargets(others, axis, page);
  const points = [origin, origin + size / 2, origin + size];
  let best: { dist: number; guide: number; value: number } | null = null;
  for (const point of points) {
    for (const target of targets) {
      const dist = Math.abs(point - target);
      if (dist <= GUIDE_REACH && (best === null || dist < best.dist)) {
        best = { dist, guide: target, value: origin + (target - point) };
      }
    }
  }
  if (!best) return { value: snap(origin), guide: null };
  return { value: best.value, guide: best.guide };
}

function anchors(box: Box, axis: "x" | "y"): number[] {
  if (axis === "x") return [box.x, box.x + box.width / 2, box.x + box.width];
  return [box.y, box.y + box.height / 2, box.y + box.height];
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(max, min));
}
