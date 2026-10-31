import { useEffect, useMemo } from "react";

import { apiFetch } from "../shared/api";
import { defaultSaved, forReader, lockedTheme, themeForReport, type MagbiTheme, type SavedThemes } from "../shared/theme";
import { useDesignerStore } from "./store";

const NONE: SavedThemes = { organisation: [], workspace: [] };

/**
 * The open report's resolved theme: the organisation's and workspace's themes,
 * a host app's pick when embedded, then what the reader turned on.
 */
export function useReportTheme(): MagbiTheme {
  const own = useDesignerStore((state) => state.report.theme);
  const host = useDesignerStore((state) => state.hostTheme);
  const saved = useDesignerStore((state) => state.savedThemes);
  const preview = useDesignerStore((state) => state.themePreview);
  const reader = useDesignerStore((state) => state.reader);
  return useMemo(() => forReader(themeForReport(host ?? own, preview ? NONE : saved), reader), [own, host, saved, preview, reader]);
}

/** True once a theme applies to the report; older reports with none keep their original look. */
export function useHasTheme(): boolean {
  const own = useDesignerStore((state) => Boolean(state.report.theme?.id || state.report.theme?.colors?.length || state.hostTheme || state.reader.contrast || state.reader.larger));
  const saved = useDesignerStore((state) => state.savedThemes);
  const preview = useDesignerStore((state) => state.themePreview);
  return own || (!preview && Boolean(lockedTheme(saved) ?? defaultSaved(saved)));
}

/** The saved themes a report in this workspace may use; none when they cannot be read. */
export async function fetchSavedThemes(workspaceId: string, token?: string | null): Promise<SavedThemes> {
  const headers = token ? { Authorization: `Bearer ${token}` } : undefined;
  try {
    const saved = await apiFetch<SavedThemes>(`/workspaces/${workspaceId}/themes`, { headers });
    return { organisation: saved.organisation ?? [], workspace: saved.workspace ?? [] };
  } catch {
    return NONE;
  }
}

/** Loads the saved themes into the store whenever the workspace changes. */
export function useSavedThemesLoader(workspaceId: string | undefined, token?: string | null): void {
  const setSavedThemes = useDesignerStore((state) => state.setSavedThemes);
  useEffect(() => {
    if (!workspaceId) return;
    let cancelled = false;
    void fetchSavedThemes(workspaceId, token).then((saved) => {
      if (!cancelled) setSavedThemes(saved);
    });
    return () => {
      cancelled = true;
    };
  }, [workspaceId, token, setSavedThemes]);
}
