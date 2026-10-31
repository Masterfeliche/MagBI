/** Phone layout: each page's own visual positions on a 360 px-wide canvas that grows downwards. */

import type { PageDefinition, PhoneLayout, PhonePosition, VisualDefinition } from "../types/report";
import { snap, type Box } from "./layout";

export const PHONE_WIDTH = 360;
export const PHONE_MIN_HEIGHT = 640;
/** How far down the designer lets a visual go. */
export const PHONE_MAX_HEIGHT = 6000;
/** Windows narrower than this read the phone layout, when the page has one. */
export const PHONE_BREAKPOINT = 768;
export const PHONE_MARGIN = 10;
export const PHONE_GAP = 10;
/** Room below the last visual in the designer, to drag a visual further down. */
export const PHONE_ROOM = 240;

const FULL = PHONE_WIDTH - 2 * PHONE_MARGIN;
const HALF = (FULL - PHONE_GAP) / 2;
/** Decorative backgrounds: they frame a desktop arrangement and mean nothing on a phone. */
const DESKTOP_ONLY = new Set(["frame"]);

export function hasPhoneLayout(page: PageDefinition | undefined): boolean {
  return (page?.phone?.visuals.length ?? 0) > 0;
}

/** Page height for the layout: the lowest visual plus a margin, never shorter than a phone screen. */
export function phoneHeight(layout: PhoneLayout | undefined, room = 0): number {
  const bottom = Math.max(0, ...(layout?.visuals ?? []).map((item) => item.y + item.height));
  return Math.max(PHONE_MIN_HEIGHT, bottom + PHONE_MARGIN + room);
}

export function phoneBoxes(page: PageDefinition | undefined): Map<string, Box> {
  return new Map((page?.phone?.visuals ?? []).map(({ id, ...box }) => [id, box]));
}

/** Shown visuals the phone layout doesn't place yet, in desktop reading order. */
export function unplacedVisuals(page: PageDefinition | undefined): VisualDefinition[] {
  if (!page) return [];
  const placed = new Set((page.phone?.visuals ?? []).map((item) => item.id));
  return readingOrder(page.visuals.filter((visual) => !visual.properties?.hidden && !placed.has(visual.id)));
}

/** A phone height for a visual: about its desktop height, kept between a tap row and a screen. */
export function phoneDefaultHeight(visual: Pick<VisualDefinition, "type" | "height">): number {
  // The header stacks its title, question and as-at line on a phone.
  if (visual.type === "header") return 200;
  // A heat matrix shows every row without scrolling inside its panel.
  if (visual.type === "heatmap") return 500;
  // A donut puts its legend under the ring.
  if (visual.type === "donut") return 440;
  if (visual.type === "slicer") return Math.min(Math.max(60, snap(visual.height)), 120);
  // Key figures keep their desktop height (the standard's 122 px minimum included); labels stay a line.
  if (visual.type === "kpi" || visual.type === "card") return Math.min(Math.max(visual.height, 124), 180);
  if (visual.type === "label") return Math.max(visual.height, 20);
  if (visual.type === "grid" || visual.type === "table" || visual.type === "matrix" || visual.type === "flow") return 400;
  return Math.min(Math.max(snap(visual.height), 60), 320);
}

/** Adds a visual full width under everything already placed. */
export function placeOnPhone(layout: PhoneLayout | undefined, visual: VisualDefinition): PhoneLayout {
  const visuals = (layout?.visuals ?? []).filter((item) => item.id !== visual.id);
  const bottom = Math.max(0, ...visuals.map((item) => item.y + item.height + PHONE_GAP));
  const y = visuals.length === 0 ? PHONE_MARGIN : bottom;
  return { visuals: [...visuals, { id: visual.id, x: PHONE_MARGIN, y, width: FULL, height: phoneDefaultHeight(visual) }] };
}

export function removeFromPhone(layout: PhoneLayout | undefined, id: string): PhoneLayout | undefined {
  if (!layout) return layout;
  return { visuals: layout.visuals.filter((item) => item.id !== id) };
}

export function setPhoneBox(layout: PhoneLayout | undefined, id: string, box: Box): PhoneLayout {
  const visuals = layout?.visuals ?? [];
  const next = clampPhoneBox(box);
  return { visuals: visuals.map((item) => (item.id === id ? { id, ...next } : item)) };
}

/** Keeps a box on the phone canvas: inside its width, below its top, above the designer's limit. */
export function clampPhoneBox(box: Box): Box {
  const width = Math.min(Math.max(box.width, 40), PHONE_WIDTH);
  const height = Math.min(Math.max(box.height, 40), PHONE_MAX_HEIGHT);
  return {
    x: Math.min(Math.max(box.x, 0), PHONE_WIDTH - width),
    y: Math.min(Math.max(box.y, 0), PHONE_MAX_HEIGHT - height),
    width,
    height,
  };
}

/**
 * A starting phone layout: shown visuals one under another in desktop reading order,
 * full width, with neighbouring slicers paired two to a row. Decorative frames are left out.
 */
export function autoPhoneLayout(page: PageDefinition): PhoneLayout {
  const visuals = readingOrder(
    page.visuals.filter((visual) => !visual.properties?.hidden && !DESKTOP_ONLY.has(visual.type)),
  );
  const placed: PhonePosition[] = [];
  let y = PHONE_MARGIN;
  for (let index = 0; index < visuals.length; index += 1) {
    const visual = visuals[index] as VisualDefinition;
    const next = visuals[index + 1];
    if (visual.type === "slicer" && next?.type === "slicer") {
      const height = Math.max(phoneDefaultHeight(visual), phoneDefaultHeight(next));
      placed.push({ id: visual.id, x: PHONE_MARGIN, y, width: HALF, height });
      placed.push({ id: next.id, x: PHONE_MARGIN + HALF + PHONE_GAP, y, width: HALF, height });
      y += height + PHONE_GAP;
      index += 1;
      continue;
    }
    const height = phoneDefaultHeight(visual);
    placed.push({ id: visual.id, x: PHONE_MARGIN, y, width: FULL, height });
    y += height + PHONE_GAP;
  }
  return { visuals: placed };
}

/**
 * Phone reading order: the header, then filters, the step chain and key figures, then
 * everything else top to bottom and left to right. A label goes with the visual under it.
 */
function readingOrder(visuals: VisualDefinition[]): VisualDefinition[] {
  const rank = (visual: VisualDefinition): number => {
    if (visual.type === "label") {
      const below = visuals
        .filter((other) => other.type !== "label" && other.y >= visual.y + visual.height && overlapsColumn(visual, other))
        .sort((a, b) => a.y - b.y)[0];
      return below ? rank(below) : TYPE_RANK.other;
    }
    return TYPE_RANK[visual.type] ?? TYPE_RANK.other;
  };
  return [...visuals].sort((a, b) => rank(a) - rank(b) || a.y - b.y || a.x - b.x);
}

const TYPE_RANK: Record<string, number> = { header: 0, slicer: 1, chain: 2, kpi: 3, card: 3, other: 4 };

function overlapsColumn(a: VisualDefinition, b: VisualDefinition): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width;
}
