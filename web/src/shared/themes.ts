/** Preset chart palettes. MSD Enterprise is the host brand. */

export interface ReportTheme {
  id: string;
  name: string;
  colors: string[];
}

export const THEMES: ReportTheme[] = [
  {
    id: "default",
    name: "Default",
    colors: ["#118DFF", "#12239E", "#E66C37", "#6B007B", "#E044A7", "#744EC2"],
  },
  {
    id: "msd",
    name: "MSD Enterprise",
    colors: ["#1B2A4A", "#2B5797", "#E8913A", "#3A7BD5", "#10B981", "#64748B"],
  },
];

export function themeById(id: string): ReportTheme {
  return THEMES.find((theme) => theme.id === id) ?? THEMES[0];
}

export function colorsFromThemeJson(json: string): string[] {
  const parsed = JSON.parse(json) as { dataColors?: unknown };
  const colors = Array.isArray(parsed.dataColors)
    ? parsed.dataColors.filter((item): item is string => typeof item === "string")
    : [];
  if (colors.length === 0) throw new Error("theme JSON needs dataColors");
  return colors;
}
