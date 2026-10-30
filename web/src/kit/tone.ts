/** The MSD status vocabulary and value formats shared by every kit visual. */

export type Tone = "good" | "watch" | "action" | "none" | "info";

export const TOKENS = {
  page: "#EEF2F7",
  surface: "#F8FAFC",
  panel: "#FFFFFF",
  strip: "#E9EEF5",
  line: "#D3DCE6",
  line2: "#E2E8EF",
  ink: "#22324A",
  muted: "#66758A",
  caption: "#5A6A80",
  crumb: "#2C4F80",
  zero: "#F3F6FA",
  data: ["#3F6FB0", "#5F8BC9", "#82A6D6", "#B3C3D8"],
} as const;

export const STATUS: Record<Tone, { color: string; ink: string; glyph: string; word: string; soft: string }> = {
  good: { color: "#4E9E77", ink: "#2F7354", glyph: "▲", word: "On track", soft: "#DCEFE5" },
  watch: { color: "#D49A55", ink: "#8F5F27", glyph: "◆", word: "Watch", soft: "#F5E3CC" },
  action: { color: "#C76E6C", ink: "#9A4442", glyph: "▼", word: "Action", soft: "#F4D9D8" },
  none: { color: "#9EABBC", ink: "#5A6A80", glyph: "–", word: "No data", soft: "#E9EDF2" },
  info: { color: "#5F8BC9", ink: "#335C96", glyph: "●", word: "Information", soft: "#DCE8F6" },
};

export function isTone(value: unknown): value is Tone {
  return typeof value === "string" && value in STATUS;
}

/**
 * A tone from a number. ``blank`` covers no value at all, ``zero`` an exact 0,
 * then the first matching step, then ``otherwise``.
 */
export interface ToneRule {
  blank?: Tone;
  zero?: Tone;
  steps?: { min?: number; max?: number; tone: Tone }[];
  otherwise?: Tone;
}

export function toneOf(value: number | null, rule: ToneRule | undefined): Tone {
  if (value === null || !Number.isFinite(value)) return rule?.blank ?? "none";
  if (value === 0 && rule?.zero) return rule.zero;
  for (const step of rule?.steps ?? []) {
    if ((step.min === undefined || value >= step.min) && (step.max === undefined || value <= step.max)) {
      return step.tone;
    }
  }
  return rule?.otherwise ?? "info";
}

/** No-data members are grey wherever they appear. */
const NO_DATA = new Set(["not recorded", "not set", "not yet counted", "unknown", "none", "(blank)", ""]);

export function isNoData(name: string): boolean {
  return NO_DATA.has(name.trim().toLowerCase());
}

export type ValueFormat = "whole" | "decimal1" | "pct0" | "pct1" | "date" | "monthYear" | "signed" | "text";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** A blank always prints "–", never "(Blank)", NaN or 0. */
export function formatValue(value: unknown, format: ValueFormat = "whole"): string {
  if (value === null || value === undefined || value === "") return "–";
  if (format === "text") return String(value);
  if (format === "date" || format === "monthYear") {
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value));
    if (!match) return String(value);
    const month = MONTHS[Number(match[2]) - 1] ?? match[2];
    return format === "date" ? `${match[3]} ${month} ${match[1]}` : `${month} ${match[1].slice(2)}`;
  }
  const number = toNumber(value);
  if (number === null) return String(value);
  switch (format) {
    case "pct0":
      return `${Math.round(number * 100).toLocaleString("en-GB")}%`;
    case "pct1":
      return `${(Math.round(number * 1000) / 10).toLocaleString("en-GB", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
    case "decimal1":
      return number.toLocaleString("en-GB", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    case "signed": {
      const text = Math.abs(number).toLocaleString("en-GB", { maximumFractionDigits: 2 });
      return number < 0 ? `−${text}` : number > 0 ? `+${text}` : "0";
    }
    default:
      return Math.round(number).toLocaleString("en-GB");
  }
}

/** Fill "{0}", "{1}" ... with already formatted values. */
export function fill(template: string, values: string[]): string {
  return template.replace(/\{(\d+)\}/g, (_match, index: string) => values[Number(index)] ?? "–");
}
