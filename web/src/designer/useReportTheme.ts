import { useMemo } from "react";

import { themeForReport, type MagbiTheme } from "../shared/theme";
import { useDesignerStore } from "./store";

/** The open report's resolved theme. */
export function useReportTheme(): MagbiTheme {
  const fields = useDesignerStore((state) => state.report.theme);
  return useMemo(() => themeForReport(fields), [fields]);
}

/** True once the report has a theme of its own; older reports keep their original look. */
export function useHasTheme(): boolean {
  return useDesignerStore((state) => Boolean(state.report.theme?.id || state.report.theme?.colors?.length));
}
