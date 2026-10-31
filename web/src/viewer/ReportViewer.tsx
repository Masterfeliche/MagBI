/** Read-only report canvas that reuses designer visuals. */

import { DndContext } from "@dnd-kit/core";
import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { Canvas } from "../designer/Canvas";
import { type CrossFilter } from "../designer/filters";
import { PAGE_HEIGHT, PAGE_WIDTH } from "../designer/layout";
import { PageTabs } from "../designer/PageTabs";
import { useDesignerStore } from "../designer/store";
import { BUILT_IN_THEMES } from "../shared/theme";
import { useSavedThemesLoader } from "../designer/useReportTheme";
import { hostThemeFrom, readContrast, saveContrast } from "./readerTheme";
import { apiFetch } from "../shared/api";
import type { ReportDefinition } from "../types/report";
import "../designer/designer.css";
import "../workspace/workspace.css";
import { fitScale, type FitMode } from "./fitScale";

export function ReportViewer({
  chrome = true,
  workspaceId: workspaceIdProp,
  reportId: reportIdProp,
}: {
  chrome?: boolean;
  workspaceId?: string;
  reportId?: string;
}) {
  const params = useParams();
  const workspaceId = workspaceIdProp ?? params.workspaceId;
  const reportId = reportIdProp ?? params.reportId;
  const [searchParams] = useSearchParams();
  const replaceReport = useDesignerStore((state) => state.replaceReport);
  const setDataAsAt = useDesignerStore((state) => state.setDataAsAt);
  const report = useDesignerStore((state) => state.report);
  const stage = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState<FitMode>("page");
  const [scale, setScale] = useState(1);
  const [datasetId, setDatasetId] = useState("");
  const [error, setError] = useState("");
  const [cross, setCross] = useState<CrossFilter | null>(null);
  const token = searchParams.get("token");
  // ?theme=<id> previews a built-in theme without saving anything (QA and theme checks).
  const previewTheme = searchParams.get("theme");
  const setThemePreview = useDesignerStore((state) => state.setThemePreview);
  const setHostTheme = useDesignerStore((state) => state.setHostTheme);
  const reader = useDesignerStore((state) => state.reader);
  const setReader = useDesignerStore((state) => state.setReader);
  useSavedThemesLoader(workspaceId, token);

  // The reader's own needs: High Contrast is remembered on this device; larger text is on for phone-width screens.
  useEffect(() => {
    setReader({ contrast: readContrast() || searchParams.get("contrast") === "1", larger: window.innerWidth < 768 });
    return () => setReader({ contrast: false, larger: false });
  }, [searchParams, setReader]);

  // An embedding app may pick the theme in the URL (?themeId=) or later with the SDK's setTheme.
  useEffect(() => {
    setHostTheme(hostThemeFrom({ id: searchParams.get("themeId") ?? undefined }));
    const listen = (event: MessageEvent) => {
      if (event.source !== window.parent || event.data?.type !== "setTheme") return;
      setHostTheme(hostThemeFrom(event.data.theme ?? {}));
      if (typeof event.data.theme?.contrast === "boolean") setReader({ contrast: event.data.theme.contrast });
    };
    window.addEventListener("message", listen);
    return () => {
      window.removeEventListener("message", listen);
      setHostTheme(null);
    };
  }, [searchParams, setHostTheme, setReader]);

  useEffect(() => {
    if (!workspaceId || !reportId) return;
    let cancelled = false;
    const headers = token ? { Authorization: `Bearer ${token}` } : undefined;
    apiFetch<{
      name: string;
      dataset_id: string;
      definition: ReportDefinition;
      last_refreshed_at?: string | null;
    }>(`/workspaces/${workspaceId}/reports/${reportId}`, { headers })
      .then((body) => {
        if (cancelled) return;
        const previewing = BUILT_IN_THEMES.some((theme) => theme.id === previewTheme);
        const preview = previewing ? { theme: { id: previewTheme as string } } : {};
        setThemePreview(previewing);
        replaceReport({ ...body.definition, ...preview, name: body.name || body.definition.name });
        setDataAsAt(body.last_refreshed_at ?? null);
        setDatasetId(body.dataset_id);
        setError("");
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Report failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceId, reportId, replaceReport, setDataAsAt, token]);

  useEffect(() => {
    const node = stage.current;
    if (!node) return;
    const measure = () => {
      setScale(fitScale(fit, node.clientWidth - 32, node.clientHeight - 32));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [fit]);

  if (error) return <p className="ws-error">{error}</p>;
  if (!workspaceId || !datasetId) return <p className="ws-loading">Loading report...</p>;

  return (
    <div className={`designer viewer${chrome ? "" : " embed"}`}>
      {chrome && (
        <div className="viewer-bar">
          <strong>{report.name}</strong>
          <div className="viewer-fits">
            <button
              type="button"
              className={reader.contrast ? "ws-btn small primary" : "ws-btn small"}
              aria-pressed={reader.contrast}
              title="Black on white with patterns, for you only; the report is not changed"
              onClick={() => {
                saveContrast(!reader.contrast);
                setReader({ contrast: !reader.contrast });
              }}
            >
              ◐ High contrast
            </button>
            <button
              type="button"
              className={reader.larger ? "ws-btn small primary" : "ws-btn small"}
              aria-pressed={reader.larger}
              title="Larger text, for you only; the report is not changed"
              onClick={() => setReader({ larger: !reader.larger })}
            >
              A+ Larger text
            </button>
            <button type="button" className={fit === "page" ? "ws-btn small primary" : "ws-btn small"} onClick={() => setFit("page")}>
              Fit to page
            </button>
            <button type="button" className={fit === "width" ? "ws-btn small primary" : "ws-btn small"} onClick={() => setFit("width")}>
              Fit to width
            </button>
          </div>
        </div>
      )}
      <DndContext>
        <div className="desk">
          <div className="stage" ref={stage} style={{ flex: 1 }}>
            <div className="stage-canvas" style={{ width: PAGE_WIDTH * scale, height: PAGE_HEIGHT * scale }}>
              <Canvas
                scale={scale}
                workspaceId={workspaceId}
                datasetId={datasetId}
                cross={cross}
                onCross={setCross}
                readOnly
              />
            </div>
          </div>
        </div>
      </DndContext>
      <PageTabs readOnly />
    </div>
  );
}
