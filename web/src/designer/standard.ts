/** Shared formatting for the dashboard standard. Colours come from the default theme. */

import { DEFAULT_THEME, type StatusToken, type Tone } from "../shared/theme";

const NO_DATA = new Set(["not recorded", "not set", "unknown", "none", ""]);

export function isNoDataLabel(value: string): boolean {
  return NO_DATA.has(value.trim().toLowerCase());
}

/** One-letter status codes some ERP queries return. */
const SHORT: Record<string, Tone> = { g: "good", w: "watch", b: "action", n: "none", f: "info" };

export function statusOf(key: string): StatusToken {
  const name = key.trim().toLowerCase();
  const tone = (SHORT[name] ?? name) as Tone;
  return DEFAULT_THEME.status[tone] ?? DEFAULT_THEME.status.none;
}

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function formatDate(value: string, pattern: "dd Mon yyyy" | "Mon yy" = "dd Mon yyyy"): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value.trim());
  if (!match) return value;
  const month = MON[Number(match[2]) - 1];
  if (!month) return value;
  if (pattern === "Mon yy") return `${month} ${match[1].slice(2)}`;
  return `${match[3]} ${month} ${match[1]}`;
}

export function displayLabel(value: string, labels: Record<string, string> = {}): string {
  return labels[value] ?? labels[value.toLowerCase()] ?? value;
}

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function layoutIssues(boxes: Box[], width = 1760, height = 990): string[] {
  const issues: string[] = [];
  boxes.forEach((box, index) => {
    if (box.x < 0 || box.y < 0 || box.x + box.width > width || box.y + box.height > height) {
      issues.push(`visual ${index + 1} sits outside the canvas`);
    }
    boxes.slice(index + 1).forEach((other, offset) => {
      const overlaps = box.x < other.x + other.width && box.x + box.width > other.x && box.y < other.y + other.height && box.y + box.height > other.y;
      if (overlaps) issues.push(`visual ${index + 1} overlaps visual ${index + offset + 2}`);
    });
  });
  return issues;
}
