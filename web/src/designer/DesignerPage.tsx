/** MagBI designer — Power BI-style report builder. */

import { DndContext, type DragEndEvent } from "@dnd-kit/core";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { apiFetch } from "../shared/api";
import { BookmarkPanel } from "./BookmarkPanel";
import { ConditionalFormatDialog } from "./ConditionalFormatDialog";
import { MeasureEditor } from "../model-editor/MeasureEditor";
import { RlsRolesDialog } from "../model-editor/RlsRolesDialog";
import { ViewAsDialog } from "../model-editor/ViewAsDialog";
import { GetDataDialog } from "../workspace/GetDataDialog";
import { RefreshPanel } from "../workspace/RefreshPanel";
import type { ReportDefinition } from "../types/report";
import { visualSpec } from "./catalog";
import { Canvas } from "./Canvas";
import { ContextMenu, type ContextMenuAction } from "./ContextMenu";
import { type CrossFilter } from "./filters";
import { PAGE_WIDTH, blankReport } from "./layout";
import { LeftPanel } from "./LeftPanel";
import { adaptDataset, type DesignerField, type DesignerTable } from "./model";
import { PageTabs } from "./PageTabs";
import { Ribbon } from "./Ribbon";
import { RightPanel } from "./RightPanel";
import { StatusBar } from "./StatusBar";
import { SelectionPane } from "./SelectionPane";
import { TooltipPreview } from "./TooltipPreview";
import { useDesignerStore } from "./store";
import { themeById } from "../shared/themes";
import { exportReport, exportVisualData } from "./exportReport";
import { visualDataOf } from "./visualData";
import { TitleBar } from "./TitleBar";
import { dropField, removeBinding, wellForDrop } from "./wells";
import { pickReport } from "./pickReport";
import { layoutIssues } from "./standard";
import "./designer.css";

export function DesignerPage() {
  const { workspaceId, datasetId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const report = useDesignerStore((s) => s.report);
  const selectedId = useDesignerStore((s) => s.selectedVisualId);
  const activePageIndex = useDesignerStore((s) => s.activePageIndex);
  const selectVisual = useDesignerStore((s) => s.selectVisual);
  const setWells = useDesignerStore((s) => s.setWells);
  const setPageFilters = useDesignerStore((s) => s.setPageFilters);
  const removeVisual = useDesignerStore((s) => s.removeVisual);
  const removeAllVisuals = useDesignerStore((s) => s.removeAllVisuals);
  const setSaveStatus = useDesignerStore((s) => s.setSaveStatus);
  const copyVisual = useDesignerStore((s) => s.copyVisual);
  const pasteVisual = useDesignerStore((s) => s.pasteVisual);
  const setProperties = useDesignerStore((s) => s.setProperties);
  const bringToFront = useDesignerStore((s) => s.bringToFront);
  const sendToBack = useDesignerStore((s) => s.sendToBack);
  const clipboard = useDesignerStore((s) => s.clipboard);
  const drillThrough = useDesignerStore((s) => s.drillThrough);
  const replaceReport = useDesignerStore((s) => s.replaceReport);
  const viewAs = useDesignerStore((s) => s.viewAs);
  const setViewAs = useDesignerStore((s) => s.setViewAs);
  const undo = useDesignerStore((s) => s.undo);
  const redo = useDesignerStore((s) => s.redo);

  const stage = useRef<HTMLDivElement>(null);
  const selectAll = useRef(false);
  const skipSave = useRef(true);
  const [autoScale, setAutoScale] = useState(1);
  const [manualZoom, setManualZoom] = useState<number | null>(null);
  const scale = manualZoom ?? autoScale;
  const [tables, setTables] = useState<DesignerTable[]>([]);
  const [modelVersion, setModelVersion] = useState(1);
  const [loadError, setLoadError] = useState("");
  const [showGetData, setShowGetData] = useState(false);
  const [showMeasure, setShowMeasure] = useState(false);
  const [showRoles, setShowRoles] = useState(false);
  const [showViewAs, setShowViewAs] = useState(false);
  const [showCondFmt, setShowCondFmt] = useState(false);
  const [showBookmarks, setShowBookmarks] = useState(false);
  const [showRefresh, setShowRefresh] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState("");
  const [cross, setCross] = useState<CrossFilter | null>(null);
  const [reportId, setReportId] = useState("");
  const [publishError, setPublishError] = useState("");
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; visualId: string | null } | null>(null);
  const [showSelection, setShowSelection] = useState(false);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; visualId: string } | null>(null);

  // --- load dataset + existing report ---
  useEffect(() => {
    if (!workspaceId || !datasetId) return;
    let cancelled = false;
    Promise.all([
      apiFetch<{ name: string; definition: unknown; model_version: number }>(
        `/workspaces/${workspaceId}/datasets/${datasetId}`,
      ),
      apiFetch<Array<{ id: string; dataset_id: string; definition: ReportDefinition }>>(
        `/workspaces/${workspaceId}/reports`,
      ).catch(() => []),
    ])
      .then(([dataset, reports]) => {
        if (cancelled) return;
        setTables(adaptDataset(dataset.definition));
        setModelVersion(dataset.model_version);
        setLoadError("");
        const saved = pickReport(reports, datasetId, searchParams.get("report"));
        if (saved) {
          replaceReport(saved.definition);
          setReportId(saved.id);
          return;
        }
        replaceReport(blankReport(dataset.name, datasetId));
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(error instanceof Error ? error.message : "Dataset failed to load");
      });
    return () => { cancelled = true; };
  }, [workspaceId, datasetId, replaceReport, searchParams]);

  useEffect(() => {
    if (!workspaceId || !reportId) return;
    if (skipSave.current) {
      skipSave.current = false;
      return;
    }
    setSaveStatus("dirty");
    const timer = window.setTimeout(() => {
      setSaveStatus("saving");
      apiFetch(`/workspaces/${workspaceId}/reports/${reportId}`, {
        method: "PUT",
        body: JSON.stringify({ definition: report }),
      })
        .then(() => setSaveStatus("saved"))
        .catch(() => setSaveStatus("dirty"));
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [report, reportId, workspaceId, setSaveStatus]);

  // --- auto-scale canvas ---
  useEffect(() => {
    const node = stage.current;
    if (!node) return;
    const measure = () => {
      const width = node.clientWidth - 32;
      setAutoScale(width > 0 ? width / PAGE_WIDTH : 1);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // --- keyboard shortcuts ---
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
        event.preventDefault();
        selectAll.current = true;
        return;
      }
      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        if (selectAll.current) removeAllVisuals();
        else if (selectedId) removeVisual(selectedId);
        selectAll.current = false;
        return;
      }
      const key = event.key.toLowerCase();
      if (!(event.ctrlKey || event.metaKey)) return;
      if (key === "z") {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
      }
      else if (key === "y") { event.preventDefault(); redo(); }
      else if (key === "c" && selectedId) { event.preventDefault(); copyVisual(selectedId); }
      else if (key === "v") { event.preventDefault(); pasteVisual(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo, removeVisual, removeAllVisuals, selectedId, copyVisual, pasteVisual]);

  // --- derived ---
  const page = report.pages[activePageIndex];
  const selected = page?.visuals.find((v) => v.id === selectedId);
  const spec = selected ? visualSpec(selected.type) : undefined;

  // --- dnd handler ---
  function onDragEnd(event: DragEndEvent) {
    const field = event.active.data.current?.field as DesignerField | undefined;
    const wellName = event.over?.data.current?.well as string | undefined;
    const visualId = event.over?.data.current?.visualId as string | undefined;
    const target = visualId ? page?.visuals.find((v) => v.id === visualId) : selected;
    if (!field || !target) return;
    const targetSpec = visualSpec(target.type);
    const well = wellName
      ? targetSpec.wells.find((w) => w.name === wellName)
      : wellForDrop(targetSpec, field, target.wells);
    if (!well) return;
    const result = dropField(target.wells, well, field);
    if (!result.accepted) return;
    setWells(target.id, result.wells);
    if (visualId) selectVisual(target.id);
  }

  function buildContextActions(visualId: string | null): ContextMenuAction[] {
    const dtPages = report.pages
      .map((p, i) => ({ page: p, index: i }))
      .filter((p) => p.page.pageType === "drillthrough");
    if (!visualId) {
      return [
        { label: "Paste", icon: "📋", disabled: !clipboard, onClick: () => pasteVisual() },
        { label: "Fit to page", icon: "⊡", onClick: () => setManualZoom(null) },
      ];
    }
    return [
      { label: "Copy", icon: "📄", onClick: () => copyVisual(visualId) },
      { label: "Paste", icon: "📋", disabled: !clipboard, onClick: () => pasteVisual() },
      { label: "Bring to front", icon: "⬆", onClick: () => bringToFront(visualId) },
      { label: "Send to back", icon: "⬇", onClick: () => sendToBack(visualId) },
      ...(dtPages.length > 0
        ? dtPages.map((dt) => ({
            label: `Drill → ${dt.page.displayName}`,
            icon: "↗",
            onClick: () => drillThrough(dt.index, page?.filters ?? []),
          }))
        : [{ label: "Drillthrough", icon: "↗", disabled: true, onClick: () => {} }]),
      { label: "Hide", icon: "👁", onClick: () => setProperties(visualId, { hidden: true }) },
      { label: "Export CSV", icon: "⬇", onClick: () => {
        const data = visualDataOf(visualId);
        if (data) exportVisualData(data.columns, data.rows, "visual", "csv");
      } },
      { label: "Export Excel", icon: "⬇", onClick: () => {
        const data = visualDataOf(visualId);
        if (data) exportVisualData(data.columns, data.rows, "visual", "xlsx");
      } },
      { label: "Show as table", icon: "⊞", disabled: true, divider: true, onClick: () => {} },
      { label: "Remove", icon: "🗑", danger: true, onClick: () => removeVisual(visualId) },
    ];
  }

  // --- publish ---
  async function reloadModel() {
    if (!workspaceId || !datasetId) return;
    const dataset = await apiFetch<{ definition: unknown; model_version: number }>(
      `/workspaces/${workspaceId}/datasets/${datasetId}`,
    );
    setTables(adaptDataset(dataset.definition));
    setModelVersion(dataset.model_version);
  }

  async function publish() {
    if (!workspaceId || !datasetId) return;
    const issues = report.pages.flatMap((page) => layoutIssues(page.visuals));
    if (issues.length > 0) {
      setPublishError(issues[0] ?? "Layout check failed");
      return;
    }
    setPublishError("");
    try {
      if (reportId) {
        await apiFetch(`/workspaces/${workspaceId}/reports/${reportId}`, {
          method: "PUT",
          body: JSON.stringify({ definition: report, is_published: true }),
        });
        return;
      }
      const created = await apiFetch<{ id: string }>(`/workspaces/${workspaceId}/reports`, {
        method: "POST",
        body: JSON.stringify({
          name: report.name,
          dataset_id: datasetId,
          definition: report,
          is_published: true,
        }),
      });
      setReportId(created.id);
    } catch (error: unknown) {
      setPublishError(error instanceof Error ? error.message : "Publish failed");
    }
  }

  return (
    <div className="designer">
      <TitleBar />
      <Ribbon
        onPublish={() => void publish()}
        onToggleSelection={() => setShowSelection((s) => !s)}
        onRefresh={() => setShowRefresh((open) => !open)}
        onGetData={() => setShowGetData(true)}
        onNewMeasure={() => setShowMeasure(true)}
        onManageRoles={() => setShowRoles(true)}
        onViewAs={() => setShowViewAs(true)}
        onModel={() => {
          if (workspaceId && datasetId) navigate(`/workspaces/${workspaceId}/datasets/${datasetId}/model`);
        }}
        onCondFormat={() => setShowCondFmt(true)}
        onBookmarks={() => setShowBookmarks(true)}
        onImportTheme={(json) => useDesignerStore.getState().importThemeJson(json)}
        onTheme={(themeId) => useDesignerStore.getState().setTheme(themeById(themeId).colors)}
        onExport={() => {
          if (stage.current) exportReport(stage.current, report.name || "report");
        }}
      />
      {showRefresh && workspaceId && datasetId && (
        <div className="refresh-drawer">
          <RefreshPanel workspaceId={workspaceId} datasetId={datasetId} onStatus={setRefreshMessage} />
        </div>
      )}
      {showGetData && workspaceId && datasetId && (
        <GetDataDialog
          workspaceId={workspaceId}
          datasetId={datasetId}
          onClose={() => setShowGetData(false)}
          onImported={() => void reloadModel()}
        />
      )}
      {viewAs && (
        <div className="view-as-banner">
          Viewing as {viewAs.roles.join(", ")}
          {viewAs.user ? ` (${viewAs.user})` : ""}
          <button type="button" className="ws-btn small" onClick={() => setViewAs(null)}>Stop</button>
        </div>
      )}
      {showRoles && workspaceId && datasetId && (
        <RlsRolesDialog
          workspaceId={workspaceId}
          datasetId={datasetId}
          modelVersion={modelVersion}
          tables={tables}
          onClose={() => setShowRoles(false)}
          onSaved={setModelVersion}
        />
      )}
      {showViewAs && workspaceId && datasetId && (
        <ViewAsDialog
          workspaceId={workspaceId}
          datasetId={datasetId}
          onClose={() => setShowViewAs(false)}
        />
      )}
      {showCondFmt && <ConditionalFormatDialog onClose={() => setShowCondFmt(false)} />}
      {showBookmarks && <BookmarkPanel onClose={() => setShowBookmarks(false)} />}
      {showMeasure && workspaceId && datasetId && (
        <MeasureEditor
          workspaceId={workspaceId}
          datasetId={datasetId}
          modelVersion={modelVersion}
          tables={tables}
          onClose={() => setShowMeasure(false)}
          onSaved={(next, version) => {
            setTables(next);
            setModelVersion(version);
          }}
        />
      )}
      <DndContext onDragEnd={onDragEnd}>
        <div className="desk">
          <LeftPanel
            tables={tables}
            filters={page?.filters ?? []}
            onFiltersChange={setPageFilters}
          />
          <div className="stage">
            <div
              className="stage-canvas"
              ref={stage}
              onMouseMove={(e) => {
                const target = (e.target as HTMLElement).closest(".visual");
                if (!target || selectedId) { setTooltip(null); return; }
                const vid = target.querySelector("[data-visual-id]")?.getAttribute("data-visual-id");
                if (vid) setTooltip({ x: e.clientX, y: e.clientY, visualId: vid });
                else setTooltip(null);
              }}
              onMouseLeave={() => setTooltip(null)}
              onContextMenu={(e) => {
                e.preventDefault();
                setTooltip(null);
                const target = (e.target as HTMLElement).closest(".visual");
                const visualId = target?.querySelector("[data-visual-id]")?.getAttribute("data-visual-id")
                  ?? (target?.classList.contains("visual") ? selectedId : null);
                setCtxMenu({ x: e.clientX, y: e.clientY, visualId: visualId ?? null });
              }}
            >
              {(loadError || publishError) && <p className="hint">{loadError || publishError}</p>}
              <Canvas
                scale={scale}
                workspaceId={workspaceId ?? ""}
                datasetId={datasetId ?? ""}
                cross={cross}
                onCross={setCross}
              />
              {showSelection && <SelectionPane onClose={() => setShowSelection(false)} />}
              {tooltip && (() => {
                const hovered = page?.visuals.find((v) => v.id === tooltip.visualId);
                return hovered ? <TooltipPreview visual={hovered} x={tooltip.x} y={tooltip.y} /> : null;
              })()}
              {ctxMenu && (
                <ContextMenu
                  x={ctxMenu.x}
                  y={ctxMenu.y}
                  actions={buildContextActions(ctxMenu.visualId)}
                  onClose={() => setCtxMenu(null)}
                />
              )}
            </div>
            <PageTabs />
          </div>
          <RightPanel
            tables={tables}
            wells={spec?.wells ?? []}
            bindings={selected?.wells ?? {}}
            onRemoveBinding={(wellName, index) => {
              if (!selected) return;
              setWells(selected.id, removeBinding(selected.wells, wellName, index));
            }}
          />
        </div>
      </DndContext>
      <StatusBar
        datasetId={datasetId ?? ""}
        zoom={scale}
        onZoomIn={() => setManualZoom(Math.min(2, (manualZoom ?? autoScale) + 0.1))}
        onZoomOut={() => setManualZoom(Math.max(0.25, (manualZoom ?? autoScale) - 0.1))}
        onFitToPage={() => setManualZoom(null)}
        refreshMessage={refreshMessage}
      />
    </div>
  );
}
