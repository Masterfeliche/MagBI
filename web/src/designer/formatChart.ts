/** Map stored format and analytics properties onto an ECharts option. */

export interface FormatProps {
  titleShow?: boolean;
  title?: string;
  titleFontSize?: number;
  titleColor?: string;
  titleAlign?: string;
  xShow?: boolean;
  xFontSize?: number;
  xColor?: string;
  yShow?: boolean;
  yUnits?: string;
  labelsShow?: boolean;
  labelsPos?: string;
  legendShow?: boolean;
  legendPos?: string;
  color?: string;
  color2?: string;
  analytics_average?: boolean;
  analytics_min?: boolean;
  analytics_max?: boolean;
  analytics_constant?: boolean;
  analytics_trend?: boolean;
  [key: string]: unknown;
}

export const DEFAULT_PALETTE = ["#118DFF", "#12239E", "#E66C37", "#6B007B", "#E044A7", "#744EC2"];

export interface NumberFormat {
  decimals?: number;
  whole?: boolean;
  units?: "none" | "thousands" | "millions" | "billions" | "auto";
  prefix?: string;
  suffix?: string;
}

/** Round, group thousands, and optionally shorten to K, M, or B. */
export function formatNumber(value: unknown, options: NumberFormat = {}): string {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return value == null ? "" : String(value);
  const decimals = options.whole ? 0 : options.decimals ?? 2;
  const units = options.units ?? "none";
  const abs = Math.abs(parsed);
  let scaled = parsed;
  let unit = "";
  const auto = units === "auto";
  if (units === "billions" || (auto && abs >= 1_000_000_000)) {
    scaled = parsed / 1_000_000_000;
    unit = "B";
  } else if (units === "millions" || (auto && abs >= 1_000_000)) {
    scaled = parsed / 1_000_000;
    unit = "M";
  } else if (units === "thousands" || (auto && abs >= 10_000)) {
    scaled = parsed / 1_000;
    unit = "K";
  }
  const textValue = scaled.toLocaleString("en-US", {
    minimumFractionDigits: unit ? 0 : decimals,
    maximumFractionDigits: unit ? 1 : decimals,
  });
  return `${options.prefix ?? ""}${textValue}${unit}${options.suffix ?? ""}`;
}

export function categoryAxisLabel(
  count: number,
  label: { show: boolean; fontSize: number; color: string },
): { show: boolean; fontSize: number; color: string; rotate: number; interval: number; overflow: string; width: number } {
  return {
    ...label,
    rotate: count > 12 ? 45 : 0,
    interval: count > 15 ? Math.ceil(count / 15) : 0,
    overflow: "truncate",
    width: 80,
  };
}

export function chartColors(props: FormatProps, theme: string[] = []): string[] {
  const base = theme.length > 0 ? theme : DEFAULT_PALETTE;
  return [text(props.color, base[0]), text(props.color2, base[1] ?? base[0]), ...base.slice(2)];
}

export function titleFrom(props: FormatProps): Record<string, unknown> | undefined {
  if (props.titleShow === false) return undefined;
  const title = typeof props.title === "string" ? props.title : "";
  if (!title) return undefined;
  const align = typeof props.titleAlign === "string" ? props.titleAlign.toLowerCase() : "left";
  return {
    text: title,
    left: align === "center" ? "center" : align === "right" ? "right" : "left",
    textStyle: {
      fontSize: number(props.titleFontSize, 14),
      color: text(props.titleColor, "#1E293B"),
      fontWeight: 600,
    },
  };
}

export function axisText(show: unknown, size: unknown, color: unknown): { show: boolean; fontSize: number; color: string } {
  return { show: show !== false, fontSize: number(size, 10), color: text(color, "#64748B") };
}

export function unitsFormatter(units: unknown): ((value: number) => string) | undefined {
  if (units === "K") return (value) => `${value / 1000}K`;
  if (units === "M") return (value) => `${value / 1_000_000}M`;
  return undefined;
}

export function labelPlacement(position: unknown): string {
  if (position === "Inside end" || position === "Center") return "inside";
  return "top";
}

export function legendFrom(props: FormatProps): { show: boolean; top?: string; left?: string } {
  if (props.legendShow === false) return { show: false };
  const pos = typeof props.legendPos === "string" ? props.legendPos.toLowerCase() : "top";
  if (pos === "left" || pos === "right") return { show: true, left: pos };
  return { show: true, top: pos === "bottom" ? "bottom" : "top" };
}

export function markLines(values: number[], props: FormatProps): { yAxis: number; name: string }[] {
  if (values.length === 0) return [];
  const lines: { yAxis: number; name: string }[] = [];
  const average = values.reduce((sum, value) => sum + value, 0) / values.length;
  if (props.analytics_average) lines.push({ yAxis: average, name: "Average" });
  if (props.analytics_min) lines.push({ yAxis: Math.min(...values), name: "Min" });
  if (props.analytics_max) lines.push({ yAxis: Math.max(...values), name: "Max" });
  if (props.analytics_constant) lines.push({ yAxis: average, name: "Constant" });
  return lines;
}

export function trendValues(values: number[]): number[] {
  const count = values.length;
  if (count === 0) return [];
  const xs = values.map((_, index) => index);
  const xMean = (count - 1) / 2;
  const yMean = values.reduce((sum, value) => sum + value, 0) / count;
  const denom = xs.reduce((sum, x) => sum + (x - xMean) ** 2, 0) || 1;
  const slope = xs.reduce((sum, x, index) => sum + (x - xMean) * (values[index] - yMean), 0) / denom;
  return xs.map((x) => yMean + slope * (x - xMean));
}

function text(value: unknown, fallback: string): string {
  return typeof value === "string" && value ? value : fallback;
}

function number(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}
