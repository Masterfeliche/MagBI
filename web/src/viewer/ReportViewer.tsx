/** Read-only report canvas that reuses designer visuals. */

import { DndContext } from "@dnd-kit/core";
import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { Canvas } from "../designer/Canvas";
import { type CrossFilter } from "../designer/filters";
import { PAGE_HEIGHT, PAGE_WIDTH } from "../designer/layout";
import { PageTabs } from "../designer/PageTabs";
import { hasPhoneLayout, PHONE_WIDTH, phoneHeight } from "../designer/phone";
import { useDesignerStore } from "../designer/store";
import { BUILT_IN_THEMES } from "../shared/theme";
import { useSavedThemesLoader } from "../designer/useReportTheme";
import { hostThemeFrom, readContrast, saveContrast } from "./readerTheme";
import { apiFetch } from "../shared/api";
import { downloadPdf } from "../shared/sharing";
import { canEdit, type Workspace } from "../types/api";
import type { ReportDefinition } from "../types/report";
import "../designer/designer.css";
import "../workspace/workspace.css";
import { fitScale, phoneScale, type FitMode } from "./fitScale";
import { useNarrowWindow } from "./useNarrowWindow";
import { AlertDialog, SubscribeDialog } from "./NotifyDialogs";
import { ShareDialog } from "./ShareDialog";

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
  const activePageIndex = useDesignerStore((state) => state.activePageIndex);
  const stage = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState<FitMode>("page");
  const [scale, setScale] = useState(1);
  const [datasetId, setDatasetId] = useState("");
  const [error, setError] = useState("");
  const [cross, setCross] = useState<CrossFilter | null>(null);
  const token = searchParams.get("token");
  // ?export=1 draws every page at full size, one per printed page, for the server's PDF export.
  const exporting = searchParams.get("export") === "1";
  const [dialog, setDialog] = useState<"share" | "subscribe" | "alerts" | null>(null);
  const [printing, setPrinting] = useState(false);
  const [notice, setNotice] = useState("");
  const [editor, setEditor] = useState(false);
  // ?theme=<id> previews a built-in theme without saving anything (QA and theme checks).
  const previewTheme = searchParams.get("theme");
  const setThemePreview = useDesignerStore((state) => state.setThemePreview);
  const setHostTheme = useDesignerStore((state) => state.setHostTheme);
  const reader = useDesignerStore((state) => state.reader);
  const setReader = useDesignerStore((state) => state.setReader);
  useSavedThemesLoader(workspaceId, token);
  // Under 768 px a page with a phone layout is drawn from it; other pages shrink to fit as before.
  const narrow = useNarrowWindow();
  const activePage = report.pages[activePageIndex];
  const phone = narrow && !exporting && hasPhoneLayout(activePage);
  const pageWidth = phone ? PHONE_WIDTH : PAGE_WIDTH;
  const pageHeight = phone ? phoneHeight(activePage?.phone) : PAGE_HEIGHT;

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

  // Only workspace editors may share; people a report is shared with aren't members at all.
  useEffect(() => {
    if (!workspaceId || token || exporting || !chrome) return;
    apiFetch<Workspace>(`/workspaces/${workspaceId}`)
      .then((workspace) => setEditor(canEdit(workspace.my_role)))
      .catch(() => setEditor(false));
  }, [workspaceId, token, exporting, chrome]);

  async function exportPdf() {
    if (!workspaceId || !reportId || printing) return;
    setPrinting(true);
    setNotice("");
    try {
      await downloadPdf(workspaceId, reportId, report.name);
    } catch (reason: unknown) {
      setNotice(reason instanceof Error ? reason.message : "Export failed");
    } finally {
      setPrinting(false);
    }
  }

  useEffect(() => {
    const node = stage.current;
    if (!node) return;
    const measure = () => {
      setScale(phone ? phoneScale(node.clientWidth) : fitScale(fit, node.clientWidth - 32, node.clientHeight - 32));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
    // The stage appears only once the report has loaded, so measure again then.
  }, [fit, datasetId, phone]);

  if (error) return <p className="ws-error">{error}</p>;
  if (!workspaceId || !datasetId) return <p className="ws-loading">Loading report...</p>;

  if (exporting) {
    return (
      <div className="designer viewer export">
        <style>{`@page { size: ${PAGE_WIDTH}px ${PAGE_HEIGHT}px; margin: 0; }`}</style>
        <DndContext>
          {report.pages.map((page, index) => (
            <div className="export-page" key={page.name ?? index} style={{ width: PAGE_WIDTH, height: PAGE_HEIGHT }}>
              <Canvas scale={1} workspaceId={workspaceId} datasetId={datasetId} cross={null} onCross={() => undefined} readOnly pageIndex={index} />
            </div>
          ))}
        </DndContext>
      </div>
    );
  }

  return (
    <div className={`designer viewer${chrome ? "" : " embed"}${narrow ? " narrow" : ""}${phone ? " phone" : ""}`}>
      {chrome && (
        <div className="viewer-bar">
          <strong>{report.name}</strong>
          <div className="viewer-fits">
            <button
              type="button"
              className={reader.contrast ? "ws-btn small primary" : "ws-btn small"}
              aria-pressed={reader.contrast}
              aria-label="High contrast"
              title="Black on white with patterns, for you only; the report is not changed"
              onClick={() => {
                saveContrast(!reader.contrast);
                setReader({ contrast: !reader.contrast });
              }}
            >
              ◐<span className="viewer-btn-word"> High contrast</span>
            </button>
            <button
              type="button"
              className={reader.larger ? "ws-btn small primary" : "ws-btn small"}
              aria-pressed={reader.larger}
              aria-label="Larger text"
              title="Larger text, for you only; the report is not changed"
              onClick={() => setReader({ larger: !reader.larger })}
            >
              A+<span className="viewer-btn-word"> Larger text</span>
            </button>
            {!phone && (
              <>
                <button type="button" className={fit === "page" ? "ws-btn small primary" : "ws-btn small"} onClick={() => setFit("page")}>
                  Fit to page
                </button>
                <button type="button" className={fit === "width" ? "ws-btn small primary" : "ws-btn small"} onClick={() => setFit("width")}>
                  Fit to width
                </button>
              </>
            )}
          </div>
          {!token && reportId && (
            <div className="viewer-fits viewer-share">
              {editor && (
                <button type="button" className="ws-btn small" onClick={() => setDialog("share")}>Share</button>
              )}
              <button type="button" className="ws-btn small" onClick={() => void exportPdf()} disabled={printing}
                title="Every page as a PDF, as you see it">
                {printing ? "Exporting…" : "Export PDF"}
              </button>
              <button type="button" className="ws-btn small" onClick={() => setDialog("subscribe")}>Subscribe</button>
              <button type="button" className="ws-btn small" onClick={() => setDialog("alerts")}>Alerts</button>
            </div>
          )}
        </div>
      )}
      {notice && <p className="ws-error viewer-notice" role="alert">{notice}</p>}
      {dialog === "share" && workspaceId && reportId && (
        <ShareDialog workspaceId={workspaceId} reportId={reportId} reportName={report.name} onClose={() => setDialog(null)} />
      )}
      {dialog === "subscribe" && reportId && (
        <SubscribeDialog reportId={reportId} reportName={report.name} onClose={() => setDialog(null)} />
      )}
      {dialog === "alerts" && reportId && <AlertDialog reportId={reportId} report={report} onClose={() => setDialog(null)} />}
      <DndContext>
        <div className="desk">
          <div className="stage" ref={stage} style={{ flex: 1 }}>
            <div className="stage-canvas" style={{ width: pageWidth * scale, height: pageHeight * scale }}>
              <Canvas
                scale={scale}
                workspaceId={workspaceId}
                datasetId={datasetId}
                cross={cross}
                onCross={setCross}
                readOnly
                layout={phone ? "phone" : "desktop"}
              />
            </div>
          </div>
        </div>
      </DndContext>
      <PageTabs readOnly />
    </div>
  );
}
