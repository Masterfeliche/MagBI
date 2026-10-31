/**
 * Report themes (``magbi.theme/1``): one set of tokens per theme, resolved in
 * layers and turned into CSS variables and ECharts options.
 */

import enterpriseLight from "@themes/enterprise-light.json";

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
  data: { categorical: string[]; sequential: string[]; diverging: string[] };
  status: Record<Tone, StatusToken>;
  type: { family: string; scale: number };
  shape: { radius: number; border: number; density: "compact" | "comfortable" };
  pattern: boolean;
}

type DeepPartial<T> = { [K in keyof T]?: T[K] extends string[] ? string[] : T[K] extends object ? DeepPartial<T[K]> : T[K] };

/** One layer of the theme stack: organisation, workspace, report or visual. */
export type ThemeLayer = DeepPartial<MagbiTheme> & { locked?: boolean };

export const BUILT_IN_THEMES: MagbiTheme[] = [enterpriseLight as MagbiTheme];
export const DEFAULT_THEME = BUILT_IN_THEMES[0];

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
  return resolveTheme(builtInTheme(fields?.id), [reportLayer(fields)]);
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
    "--mb-radius": `${theme.shape.radius}px`,
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
  const axisLabel = { color: theme.text.muted, fontSize: 11, fontFamily: family };
  return {
    base: { color: theme.data.categorical, textStyle: { fontFamily: family, color: theme.text.ink }, animationDuration: 300 },
    axisLabel,
    axisLine: { lineStyle: { color: theme.surface.grid } },
    splitLine: { lineStyle: { color: theme.surface.grid } },
    legendText: { color: theme.text.muted, fontSize: 11 },
  };
}
