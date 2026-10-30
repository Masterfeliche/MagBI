/** Shared formatting for the ERP Native dashboard standard. */

export const ERP_NATIVE = {
  page: "#EEF2F7",
  panel: "#FFFFFF",
  strip: "#E9EEF5",
  line: "#D3DCE6",
  ink: "#22324A",
  muted: "#66758A",
  data: ["#3F6FB0", "#5F8BC9", "#82A6D6", "#B3C3D8"],
  good: "#4E9E77",
  watch: "#D49A55",
  action: "#C76E6C",
  none: "#9EABBC",
  info: "#5F8BC9",
} as const;

const NO_DATA = new Set(["not recorded", "not set", "unknown", "none", ""]);

export function isNoDataLabel(value: string): boolean {
  return NO_DATA.has(value.trim().toLowerCase());
}

const STATUS: Record<string, { color: string; ink: string; glyph: string; word: string }> = {
  good: { color: ERP_NATIVE.good, ink: "#2F7354", glyph: "▲", word: "On track" },
  g: { color: ERP_NATIVE.good, ink: "#2F7354", glyph: "▲", word: "On track" },
  watch: { color: ERP_NATIVE.watch, ink: "#8F5F27", glyph: "◆", word: "Watch" },
  w: { color: ERP_NATIVE.watch, ink: "#8F5F27", glyph: "◆", word: "Watch" },
  action: { color: ERP_NATIVE.action, ink: "#9A4442", glyph: "▼", word: "Action" },
  b: { color: ERP_NATIVE.action, ink: "#9A4442", glyph: "▼", word: "Action" },
  none: { color: ERP_NATIVE.none, ink: "#5A6A80", glyph: "–", word: "No data" },
  n: { color: ERP_NATIVE.none, ink: "#5A6A80", glyph: "–", word: "No data" },
  info: { color: ERP_NATIVE.info, ink: "#335C96", glyph: "●", word: "Information" },
  f: { color: ERP_NATIVE.info, ink: "#335C96", glyph: "●", word: "Information" },
};

export function statusOf(key: string): { color: string; ink: string; glyph: string; word: string } {
  return STATUS[key.trim().toLowerCase()] ?? STATUS.none;
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
