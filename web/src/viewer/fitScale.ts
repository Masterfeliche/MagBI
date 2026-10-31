import { PAGE_HEIGHT, PAGE_WIDTH } from "../designer/layout";
import { PHONE_WIDTH } from "../designer/phone";

export type FitMode = "width" | "page";

export function fitScale(
  mode: FitMode,
  containerWidth: number,
  containerHeight: number,
  pageWidth = PAGE_WIDTH,
  pageHeight = PAGE_HEIGHT,
): number {
  const widthScale = containerWidth > 0 ? containerWidth / pageWidth : 1;
  if (mode === "width") return widthScale;
  const heightScale = containerHeight > 0 ? containerHeight / pageHeight : 1;
  return Math.min(widthScale, heightScale);
}

/** Most a phone layout is enlarged: past this a small tablet would show oversized visuals. */
export const PHONE_MAX_SCALE = 1.25;

/** The phone layout across the window's width, edge to edge. */
export function phoneScale(containerWidth: number, phoneWidth = PHONE_WIDTH): number {
  if (containerWidth <= 0) return 1;
  return Math.min(containerWidth / phoneWidth, PHONE_MAX_SCALE);
}
