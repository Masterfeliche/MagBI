/**
 * Report themes (``magbi.theme/1``): one set of tokens per theme, resolved in
 * layers and turned into CSS variables and ECharts options.
 */

import classic from "@themes/classic.json";
import enterpriseLight from "@themes/enterprise-light.json";
import finance from "@themes/finance.json";
import government from "@themes/government.json";
import health from "@themes/health.json";
import highContrast from "@themes/high-contrast.json";
import mobile from "@themes/mobile.json";
import presentation from "@themes/presentation.json";
import retail from "@themes/retail.json";

export type Tone = "good" | "watch" | "action" | "none" | "info";

export interface StatusToken {
  color: string;
  ink: string;
  soft: string;
  glyph: string;
  word: string;
}

export interface MagbiTheme {
  id: string;
  name: string;
  description?: string;
  order?: number;
  mode: "light" | "dark";
  surface: {
    page: string;
    panel: string;
    strip: string;
    frame: string;
    line: string;
    lineStrong: string;
    grid: string;
    zero: string;
    selected: string;
    selectedLine: string;
    overlay: string;
    focus: string;
  };
  text: { ink: string; muted: string; caption: string; accent: string; onData: string };
  /** ``ramp`` chart colours are one hue in light-to-dark steps; ``categorical`` ones are distinct hues. */
  data: { style?: "ramp" | "categorical"; categorical: string[]; sequential: string[]; diverging: string[] };
  status: Record<Tone, StatusToken>;
  /** ``scale`` multiplies every font size; the layout itself does not move. */
  type: { family: string; scale: number; numberWeight?: number };
  /** ``touch`` is the smallest height of anything a reader taps, in px. */
  shape: { radius: number; border: number; density: "compact" | "comfortable"; touch?: number };
  chart: { gridlines: boolean };
  /** Chart series carry a pattern as well as a colour. */
  pattern: boolean;
  /** The smallest text contrast the theme promises (4.5 is WCAG AA, 7 is AAA). */
  accessibility: { contrast: number };
}

type DeepPartial<T> = { [K in keyof T]?: T[K] extends string[] ? string[] : T[K] extends object ? DeepPartial<T[K]> : T[K] };

/** One layer of the theme stack: organisation, workspace, report or visual. */
export type ThemeLayer = DeepPartial<MagbiTheme> & { locked?: boolean };

type ThemeFile = ThemeLayer & { id: string; extends?: string };

/** Theme files as written: a file may extend another and change only what differs. */
const FILES = [enterpriseLight, classic, health, finance, government, retail, mobile, presentation, highContrast] as ThemeFile[];

function fromFile(file: ThemeFile): MagbiTheme {
  const parent = file.extends ? FILES.find((other) => other.id === file.extends) : undefined;
  const { extends: _parent, ...own } = file;
  void _parent;
  return parent ? merge(fromFile(parent), own) : (own as MagbiTheme);
}

/** The gallery order: the default first, then by each file's ``order``. */
export const BUILT_IN_THEMES: MagbiTheme[] = FILES.map(fromFile).sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
export const DEFAULT_THEME = BUILT_IN_THEMES.find((theme) => theme.id === "enterprise-light") as MagbiTheme;

export function builtInTheme(id: string | undefined): MagbiTheme {
  return BUILT_IN_THEMES.find((theme) => theme.id === id) ?? DEFAULT_THEME;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function merge<T>(base: T, layer: unknown): T {
  if (!isObject(base) || !isObject(layer)) return (layer === undefined ? base : layer) as T;
  const out: Record<string, unknown> = { ...base };
  for (const [key, value] of Object.entries(layer)) {
    if (key === "locked" || value === undefined) continue;
    out[key] = merge(out[key], value);
  }
  return out as T;
}

/**
 * Later layers win. A locked layer keeps everything below it from changing
 * the theme, except the chart colours.
 */
export function resolveTheme(base: MagbiTheme, layers: (ThemeLayer | undefined)[]): MagbiTheme {
  let theme = base;
  let locked = false;
  for (const layer of layers) {
    if (!layer) continue;
    const allowed: ThemeLayer = locked ? (layer.data?.categorical ? { data: { categorical: layer.data.categorical } } : {}) : layer;
    theme = merge(theme, allowed);
    if (layer.locked) locked = true;
  }
  return theme;
}

/** The theme stored on a report today: a base id, chart colours and a page background. */
export interface ReportThemeFields {
  id?: string;
  colors?: string[];
  font?: string;
  background?: string;
  overrides?: ThemeLayer;
}

export function reportLayer(fields: ReportThemeFields | undefined): ThemeLayer | undefined {
  if (!fields) return undefined;
  const layer: ThemeLayer = {};
  if (fields.colors?.length) layer.data = { categorical: fields.colors };
  if (fields.background) layer.surface = { page: fields.background };
  if (fields.font) layer.type = { family: fields.font };
  return layer;
}

export function themeForReport(fields: ReportThemeFields | undefined): MagbiTheme {
  return resolveTheme(builtInTheme(fields?.id), [fields?.overrides, reportLayer(fields)]);
}

/** A stored colour may be a surface or text token name ("frame", "line") or a literal colour. */
export function tokenColour(theme: MagbiTheme, value: string | undefined, fallback: string): string {
  const name = value ?? fallback;
  const surface = theme.surface as Record<string, string>;
  const text = theme.text as Record<string, string>;
  return surface[name] ?? text[name] ?? name;
}

/** CSS custom properties for a theme, set on the root of each themed element. */
export function cssVars(theme: MagbiTheme): Record<string, string> {
  const vars: Record<string, string> = {
    "--mb-font": theme.type.family,
    "--mb-scale": String(theme.type.scale),
    "--mb-number-weight": String(theme.type.numberWeight ?? 700),
    "--mb-radius": `${theme.shape.radius}px`,
    "--mb-border": `${theme.shape.border}px`,
    "--mb-touch": `${theme.shape.touch ?? 0}px`,
  };
  for (const [name, value] of Object.entries(theme.surface)) vars[`--mb-${name}`] = value;
  for (const [name, value] of Object.entries(theme.text)) vars[`--mb-${name}`] = value;
  theme.data.categorical.forEach((value, index) => (vars[`--mb-data-${index + 1}`] = value));
  for (const [tone, token] of Object.entries(theme.status)) {
    vars[`--mb-${tone}`] = token.color;
    vars[`--mb-${tone}-ink`] = token.ink;
    vars[`--mb-${tone}-soft`] = token.soft;
  }
  return vars;
}

/** ``#3F6FB0`` and an alpha as an rgba() string. */
export function withAlpha(hex: string, alpha: number): string {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  if (!match) return hex;
  const [r, g, b] = match.slice(1).map((part) => parseInt(part, 16));
  return `rgba(${r},${g},${b},${Number(alpha.toFixed(2))})`;
}

/** The parts of an ECharts option every themed chart shares. */
export function buildEChartsTheme(theme: MagbiTheme) {
  const family = theme.type.family.replace(/"/g, "");
  /** A font size in the theme's scale. */
  const size = (px: number) => Math.round(px * theme.type.scale * 10) / 10;
  const axisLabel = { color: theme.text.muted, fontSize: size(11), fontFamily: family };
  return {
    base: {
      color: theme.data.categorical,
      textStyle: { fontFamily: family, color: theme.text.ink },
      animationDuration: 300,
      // Patterns on every series, so colour is never the only difference.
      ...(theme.pattern ? { aria: { enabled: true, decal: { show: true } } } : {}),
    },
    size,
    axisLabel,
    axisLine: { lineStyle: { color: theme.surface.grid, width: theme.shape.border } },
    splitLine: { show: theme.chart.gridlines, lineStyle: { color: theme.surface.grid } },
    legendText: { color: theme.text.muted, fontSize: size(11) },
  };
}
