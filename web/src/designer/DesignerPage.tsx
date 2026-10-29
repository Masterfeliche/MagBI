/** Power BI-style designer. Filters and Build are rails; only one pane is open. */

import { DndContext, type DragEndEvent } from "@dnd-kit/core";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { apiFetch } from "../shared/api";
import type { ReportDefinition } from "../types/report";
import { VISUALS, visualSpec } from "./catalog";
import { Canvas } from "./Canvas";
import { DataPane } from "./DataPane";
import { FilterPane } from "./FilterPane";
import { type CrossFilter } from "./filters";
import { PAGE_WIDTH, blankReport } from "./layout";
import { adaptDataset, type DesignerField, type DesignerTable } from "./model";
import { useDesignerStore } from "./store";
import { dropField, removeBinding, wellForDrop } from "./wells";
import { WellsPanel } from "./WellsPanel";
import "./designer.css";

type Pane = "closed" | "filters" | "build";

export function DesignerPage() {
  const { workspaceId, datasetId } = useParams();
  const report = useDesignerStore((state) => state.report);
  const selectedId = useDesignerStore((state) => state.selectedVisualId);
  const addVisual = useDesignerStore((state) => state.addVisual);
  const setWells = useDesignerStore((state) => state.setWells);
  const selectVisual = useDesignerStore((state) => state.selectVisual);
  const removeVisual = useDesignerStore((state) => state.removeVisual);
  const setPageFilters = useDesignerStore((state) => state.setPageFilters);
  const setFormat = useDesignerStore((state) => state.setFormat);
  const replaceReport = useDesignerStore((state) => state.replaceReport);
  const stage = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [pane, setPane] = useState<Pane>("closed");
  const [tab, setTab] = useState<"visuals" | "format">("visuals");
  const [tables, setTables] = useState<DesignerTable[]>([]);
  const [loadError, setLoadError] = useState("");
  const undo = useDesignerStore((state) => state.undo);
  const redo = useDesignerStore((state) => state.redo);
  const history = useDesignerStore((state) => state.history);
  const [cross, setCross] = useState<CrossFilter | null>(null);
  const [reportId, setReportId] = useState("");
  const [publishError, setPublishError] = useState("");
  const [title, setTitle] = useState("");
  const [color, setColor] = useState("#118DFF");

  useEffect(() => {
    if (!workspaceId || !datasetId) return;
    let cancelled = false;
    Promise.all([
      apiFetch<{ name: string; definition: unknown }>(
        `/workspaces/${workspaceId}/datasets/${datasetId}`,
      ),
      apiFetch<Array<{ id: string; dataset_id: string; definition: ReportDefinition }>>(
        `/workspaces/${workspaceId}/reports`,
      ).catch(() => []),
    ])
      .then(([dataset, reports]) => {
        if (cancelled) return;
        setTables(adaptDataset(dataset.definition));
        setLoadError("");
        const saved = reports.find((report) => report.dataset_id === datasetId);
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
    return () => {
      cancelled = true;
    };
  }, [workspaceId, datasetId, replaceReport]);

  const selected = report.pages[0]?.visuals.find((visual) => visual.id === selectedId);
  const spec = selected ? visualSpec(selected.type) : undefined;

  function onDragEnd(event: DragEndEvent) {
    const field = event.active.data.current?.field as DesignerField | undefined;
    const wellName = event.over?.data.current?.well as string | undefined;
    const visualId = event.over?.data.current?.visualId as string | undefined;
    const target = visualId
      ? report.pages[0]?.visuals.find((visual) => visual.id === visualId)
      : selected;
    if (!field || !target) return;
    const targetSpec = visualSpec(target.type);
    const well = wellName
      ? targetSpec.wells.find((item) => item.name === wellName)
      : wellForDrop(targetSpec, field, target.wells);
    if (!well) return;
    const result = dropField(target.wells, well, field);
    if (!result.accepted) return;
    setWells(target.id, result.wells);
    if (visualId) selectVisual(target.id);
  }

  useEffect(() => {
    const node = stage.current;
    if (!node) return;
    const measure = () => {
      const width = node.clientWidth - 32;
      setScale(width > 0 ? width / PAGE_WIDTH : 1);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [pane]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) {
        return;
      }
      if ((event.key === "Delete" || event.key === "Backspace") && selectedId) {
        event.preventDefault();
        removeVisual(selectedId);
        return;
      }
      const key = event.key.toLowerCase();
      if (!(event.ctrlKey || event.metaKey)) return;
      if (key === "z") {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
      } else if (key === "y") {
        event.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo, removeVisual, selectedId]);

  async function publish() {
    if (!workspaceId || !datasetId) return;
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

  function toggle(next: Pane) {
    setPane((current) => (current === next ? "closed" : next));
  }

  return (
    <div className="designer">
      <header className="ribbon">
        <strong className="report-name">{report.name}</strong>
        <button type="button" disabled={history.past.length === 0} onClick={undo}>
          Undo
        </button>
        <button type="button" disabled={history.future.length === 0} onClick={redo}>
          Redo
        </button>
        <button type="button" className="publish" onClick={() => void publish()}>
          Publish
        </button>
      </header>
      <DndContext onDragEnd={onDragEnd}>
      <div className="desk">
        <div className="stage" ref={stage}>
          <div className="page-tabs">
            <span className="page-tab">Page 1</span>
          </div>
          {(loadError || publishError) && <p className="hint">{loadError || publishError}</p>}
          <Canvas
            scale={scale}
            workspaceId={workspaceId ?? ""}
            datasetId={datasetId ?? ""}
            cross={cross}
            onCross={setCross}
          />
        </div>
        {pane !== "closed" && (
          <aside className="pane">
            {pane === "filters" ? (
              <FilterPane
                tables={tables}
                filters={report.pages[0]?.filters ?? []}
                onChange={setPageFilters}
              />
            ) : (
              <>
                <div className="tabs">
                  <button type="button" className={tab === "visuals" ? "on" : ""} onClick={() => setTab("visuals")}>
                    Visuals
                  </button>
                  <button
                    type="button"
                    className={tab === "format" ? "on" : ""}
                    onClick={() => {
                      setTab("format");
                      setTitle(typeof selected?.properties?.title === "string" ? selected.properties.title : "");
                      setColor(typeof selected?.properties?.color === "string" ? selected.properties.color : "#118DFF");
                    }}
                  >
                    Format
                  </button>
                </div>
                {tab === "visuals" ? (
                  <>
                    <DataPane tables={tables} />
                    <div className="gallery">
                      {VISUALS.map((item) => (
                        <button key={item.type} type="button" onClick={() => addVisual(item.type)}>
                          {item.displayName}
                        </button>
                      ))}
                    </div>
                    <WellsPanel
                      wells={spec?.wells ?? []}
                      bindings={selected?.wells ?? {}}
                      onRemove={(wellName, index) => {
                        if (!selected) return;
                        setWells(selected.id, removeBinding(selected.wells, wellName, index));
                      }}
                    />
                  </>
                ) : selected ? (
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      setFormat(selected.id, title, color);
                    }}
                  >
                    <label className="stack">
                      Title
                      <input value={title} onChange={(event) => setTitle(event.target.value)} />
                    </label>
                    <label className="stack">
                      Color
                      <input type="color" value={color} onChange={(event) => setColor(event.target.value)} />
                    </label>
                    <button type="submit">Apply</button>
                  </form>
                ) : (
                  <p className="hint">Select a visual to set its title and color.</p>
                )}
              </>
            )}
          </aside>
        )}
        <div className="rails">
          <button type="button" className={pane === "filters" ? "rail on" : "rail"} onClick={() => toggle("filters")}>
            Filters
          </button>
          <button type="button" className={pane === "build" ? "rail on" : "rail"} onClick={() => toggle("build")}>
            Build
          </button>
        </div>
      </div>
      </DndContext>
    </div>
  );
}
