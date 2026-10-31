/** The reader's theme choices and an embedding app's theme pick. */

import { BUILT_IN_THEMES, type ThemeLayer } from "../shared/theme";
import type { ThemeOverrides } from "../types/report";

const CONTRAST_KEY = "magbi.reader.highContrast";

/** High Contrast is remembered per browser; storage may be blocked, so failures read as off. */
export function readContrast(): boolean {
  try {
    return window.localStorage.getItem(CONTRAST_KEY) === "1";
  } catch {
    return false;
  }
}

export function saveContrast(on: boolean): void {
  try {
    if (on) window.localStorage.setItem(CONTRAST_KEY, "1");
    else window.localStorage.removeItem(CONTRAST_KEY);
  } catch {
    /* storage blocked: the switch still works for this visit */
  }
}

/**
 * A host app's pick: a built-in or saved theme id and changes on top. It
 * stands in for the report's own theme; a locked organisation theme still wins.
 */
export function hostThemeFrom(theme: { id?: string; overrides?: ThemeLayer }): ThemeOverrides | null {
  const id = theme.id && (BUILT_IN_THEMES.some((item) => item.id === theme.id) || theme.id.startsWith("saved:")) ? theme.id : undefined;
  const overrides = theme.overrides && typeof theme.overrides === "object" ? theme.overrides : undefined;
  if (!id && !overrides) return null;
  return { ...(id ? { id } : {}), ...(overrides ? { overrides } : {}) };
}
