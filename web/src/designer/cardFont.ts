/** Pick the largest font that fits a card value in width×0.9 and height×0.4. */

export const CARD_FONT_MIN = 12;
export const CARD_WIDTH_RATIO = 0.9;
export const CARD_HEIGHT_RATIO = 0.4;

export function fitCardFontSize(
  text: string,
  boxWidth: number,
  boxHeight: number,
  measure: (fontSize: number, text: string) => number,
): number {
  const maxWidth = Math.max(0, boxWidth * CARD_WIDTH_RATIO);
  const maxHeight = Math.max(CARD_FONT_MIN, boxHeight * CARD_HEIGHT_RATIO);
  if (maxWidth <= 0) return CARD_FONT_MIN;
  let lo = CARD_FONT_MIN;
  let hi = Math.floor(maxHeight);
  let best = CARD_FONT_MIN;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (measure(mid, text) <= maxWidth) {
      best = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return best;
}

export function canvasTextWidth(fontFamily: string): (fontSize: number, text: string) => number {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  return (fontSize, text) => {
    if (!ctx) return text.length * fontSize * 0.6;
    ctx.font = `600 ${fontSize}px ${fontFamily}`;
    return ctx.measureText(text).width;
  };
}
