import { PAGE_HEIGHT, PAGE_WIDTH } from "../designer/layout";

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
