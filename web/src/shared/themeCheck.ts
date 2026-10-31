/**
 * The theme checks, the same rules as ``server/magbi/themes/validate.py``:
 * readable text, chart colours that can be told apart (also with colour
 * blindness), and statuses that stay distinct and are not reused as chart colours.
 */

import type { MagbiTheme, Tone } from "./theme";

type Matrix = [number[], number[], number[]];

// Machado et al. (2009) full-severity simulation matrices, in linear RGB.
const CVD: Record<string, Matrix> = {
  protanopia: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
  deuteranopia: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.01182, 0.04294, 0.968881]],
  tritanopia: [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.3039]],
};
const NORMAL_MIN = 15;
const RAMP_MIN = 8;
const CVD_MIN = 6;
const STATUS_MIN = 12;
const TEXT_ON = ["page", "panel", "frame", "strip"] as const;
const ALERTS: Tone[] = ["good", "watch", "action"];

function channels(hex: string): [number, number, number] {
  const value = hex.replace("#", "");
  return [0, 2, 4].map((at) => parseInt(value.slice(at, at + 2), 16) / 255) as [number, number, number];
}

function linear(channel: number): number {
  return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
}

/** WCAG 2 contrast ratio of two hex colours. */
export function contrast(a: string, b: string): number {
  const luminance = (hex: string) => {
    const [r, g, bl] = channels(hex).map(linear);
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

function oklab([r, g, b]: number[]): number[] {
  const lms = [
    0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b,
    0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b,
    0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b,
  ].map(Math.cbrt);
  return [
    0.2104542553 * lms[0] + 0.793617785 * lms[1] - 0.0040720468 * lms[2],
    1.9779984951 * lms[0] - 2.428592205 * lms[1] + 0.4505937099 * lms[2],
    0.0259040371 * lms[0] + 0.7827717662 * lms[1] - 0.808675766 * lms[2],
  ];
}

/** OKLab distance x 100 between two colours as seen with normal vision or a colour blindness. */
export function distance(a: string, b: string, vision: "normal" | keyof typeof CVD = "normal"): number {
  const seen = (hex: string) => {
    let rgb = channels(hex).map(linear);
    const matrix = CVD[vision];
    if (matrix) rgb = matrix.map((row) => Math.min(1, Math.max(0, row.reduce((sum, m, i) => sum + m * rgb[i], 0))));
    return oklab(rgb);
  };
  const [x, y] = [seen(a), seen(b)];
  return 100 * Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]);
}

const isHex = (value: string) => /^#[0-9a-f]{6}$/i.test(value);

/** Every rule the theme breaks, in plain words; empty when it passes. */
export function themeProblems(theme: MagbiTheme): string[] {
  const found: string[] = [];
  const need = theme.accessibility?.contrast ?? 4.5;
  const { surface, text, status } = theme;
  const readable = (fg: string, bg: string, label: string, minimum = need) => {
    if (!isHex(fg) || !isHex(bg)) return;
    const ratio = contrast(fg, bg);
    if (ratio < minimum) found.push(`${label} is hard to read (contrast ${ratio.toFixed(2)}, needs ${minimum})`);
  };
  for (const where of TEXT_ON) {
    readable(text.ink, surface[where], `Text on ${where}`);
    readable(text.muted, surface[where], `Muted text on ${where}`);
    readable(text.caption, surface[where], `Captions on ${where}`);
  }
  readable(text.accent, surface.page, "Accent text on the page");
  for (const [tone, token] of Object.entries(status)) {
    readable(token.ink, token.soft, `The ${token.word} label on its pill`);
    readable(token.ink, surface.panel, `The ${token.word} label on a panel`);
    void tone;
  }
  const colours = theme.data.categorical.filter(isHex);
  if (colours[0]) readable(text.onData, colours[0], "Labels on the first chart colour", 3);

  const floor = theme.data.style === "ramp" ? RAMP_MIN : NORMAL_MIN;
  colours.slice(1).forEach((b, index) => {
    const a = colours[index];
    if (distance(a, b) < floor) found.push(`Chart colours ${a} and ${b} are too alike`);
    for (const vision of Object.keys(CVD)) {
      if (distance(a, b, vision) < CVD_MIN) found.push(`Chart colours ${a} and ${b} look the same with ${vision}`);
    }
  });
  ALERTS.forEach((a, index) => {
    for (const b of ALERTS.slice(index + 1)) {
      if (distance(status[a].color, status[b].color) < STATUS_MIN) found.push(`${status[a].word} and ${status[b].word} look the same`);
    }
    for (const colour of colours) {
      if (distance(status[a].color, colour) < STATUS_MIN) found.push(`Chart colour ${colour} looks like the ${status[a].word} status`);
    }
  });
  return found;
}
