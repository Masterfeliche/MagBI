/**
 * Theme files in and out. Import reads a Power BI report theme or a MagBI
 * theme; export writes a Power BI theme that also carries the full MagBI
 * theme under ``magbi``, so it opens in Power BI and round-trips here.
 */

import type { MagbiTheme, ThemeLayer } from "./theme";

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function colour(value: unknown): string | undefined {
  return typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value) ? value.toUpperCase() : undefined;
}

function at(value: unknown, ...path: (string | number)[]): unknown {
  let here = value;
  for (const key of path) {
    if (Array.isArray(here) && typeof key === "number") here = here[key];
    else if (isObject(here) && typeof key === "string") here = here[key];
    else return undefined;
  }
  return here;
}

/** Drops keys whose value is undefined, and objects left empty. */
function prune<T>(value: T): T {
  if (!isObject(value)) return value;
  const out: Json = {};
  for (const [key, inner] of Object.entries(value)) {
    const kept = prune(inner);
    if (kept === undefined || (isObject(kept) && Object.keys(kept).length === 0)) continue;
    out[key] = kept;
  }
  return out as T;
}

export interface ImportedTheme {
  name: string;
  /** The built-in theme the file builds on, when it says. */
  base?: string;
  layer: ThemeLayer;
}

/** Reads a Power BI theme JSON or a MagBI theme; throws with a plain reason when it is neither. */
export function importThemeFile(text: string): ImportedTheme {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("The file is not valid JSON.");
  }
  if (!isObject(parsed)) throw new Error("The file is not a theme.");
  const own = isObject(parsed.magbi) ? parsed.magbi : parsed.$schema === "magbi.theme/1" ? parsed : null;
  if (own) {
    const { id, extends: base, ...layer } = own as Json;
    return { name: String(own.name ?? parsed.name ?? "Imported theme"), base: typeof base === "string" ? base : typeof id === "string" ? id : undefined, layer: layer as ThemeLayer };
  }

  const dataColors = Array.isArray(parsed.dataColors) ? parsed.dataColors.map(colour).filter((item): item is string => Boolean(item)) : [];
  const family = at(parsed, "textClasses", "label", "fontFace") ?? at(parsed, "textClasses", "callout", "fontFace");
  const layer: ThemeLayer = prune({
    name: typeof parsed.name === "string" ? parsed.name : undefined,
    surface: {
      page: colour(at(parsed, "visualStyles", "page", "*", "background", 0, "color", "solid", "color")),
      panel: colour(parsed.background),
      strip: colour(parsed.secondaryBackground) ?? colour(parsed.backgroundLight),
      line: colour(parsed.backgroundNeutral),
      selectedLine: colour(parsed.tableAccent),
    },
    text: {
      ink: colour(parsed.foreground) ?? colour(parsed.firstLevelElements),
      muted: colour(parsed.secondLevelElements) ?? colour(parsed.foregroundNeutralSecondary),
      caption: colour(parsed.secondLevelElements) ?? colour(parsed.foregroundNeutralSecondary),
      accent: colour(parsed.tableAccent),
    },
    data: {
      ...(dataColors.length ? { style: "categorical" as const, categorical: dataColors } : {}),
      sequential: colour(parsed.minimum) && colour(parsed.maximum) ? [colour(parsed.minimum) as string, colour(parsed.maximum) as string] : undefined,
      diverging:
        colour(parsed.bad) && colour(parsed.center) && colour(parsed.good)
          ? [colour(parsed.bad) as string, colour(parsed.center) as string, colour(parsed.good) as string]
          : undefined,
    },
    status: {
      good: { color: colour(parsed.good) },
      watch: { color: colour(parsed.neutral) },
      action: { color: colour(parsed.bad) },
    },
    type: { family: typeof family === "string" ? family : undefined },
  } as ThemeLayer);
  const meaningful = Object.keys(layer).filter((key) => key !== "name");
  if (meaningful.length === 0) throw new Error("The file has no theme colours MagBI can read (dataColors, background, foreground, good, bad…).");
  return { name: typeof parsed.name === "string" ? parsed.name : "Imported theme", layer };
}

/** A Power BI report theme for ``theme``, with the whole MagBI theme under ``magbi``. */
export function exportThemeFile(theme: MagbiTheme): string {
  const fontFace = theme.type.family.replace(/"/g, "");
  const text = { fontFace, color: theme.text.ink };
  const file = {
    name: theme.name,
    dataColors: theme.data.categorical,
    background: theme.surface.panel,
    secondaryBackground: theme.surface.strip,
    backgroundNeutral: theme.surface.line,
    foreground: theme.text.ink,
    firstLevelElements: theme.text.ink,
    secondLevelElements: theme.text.muted,
    tableAccent: theme.text.accent,
    good: theme.status.good.color,
    neutral: theme.status.watch.color,
    bad: theme.status.action.color,
    minimum: theme.data.sequential[0],
    center: theme.data.diverging[1],
    maximum: theme.data.sequential[theme.data.sequential.length - 1],
    textClasses: { callout: text, title: text, header: text, label: { ...text, color: theme.text.muted } },
    visualStyles: { page: { "*": { background: [{ color: { solid: { color: theme.surface.page } }, transparency: 0 }] } } },
    magbi: { $schema: "magbi.theme/1", ...theme },
  };
  return `${JSON.stringify(file, null, 2)}\n`;
}
