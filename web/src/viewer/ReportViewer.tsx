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
        const preview = BUILT_IN_THEMES.some((theme) => theme.id === previewTheme) ? { theme: { id: previewTheme as string } } : {};
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
