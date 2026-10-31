/** Free-form page. Positions are page pixels; pointer deltas are divided by the CSS scale. */

import { useDroppable } from "@dnd-kit/core";
import { useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";

import { isKitType } from "../kit/query";
import { VisualView } from "./Charts";
import { filtersForVisual, groupingOf, toggleCrossFilter, type CrossFilter } from "./filters";
import { axisTargets, moveWithGuides, snapAxis, type Guide } from "./guides";
import {
  PAGE_HEIGHT,
  PAGE_WIDTH,
  pageOffset,
  pagePoint,
  resizeBox,
  type Box,
  type ResizeHandle,
} from "./layout";
import { useDesignerStore } from "./store";
import { useReportTheme } from "./useReportTheme";

export function Canvas({
  scale,
  workspaceId,
  datasetId,
  cross,
  onCross,
  readOnly = false,
}: {
  scale: number;
  workspaceId: string;
  datasetId: string;
  cross: CrossFilter | null;
  onCross: (next: CrossFilter | null) => void;
  readOnly?: boolean;
}) {
  const report = useDesignerStore((state) => state.report);
  const theme = useReportTheme();
  const selectedId = useDesignerStore((state) => state.selectedVisualId);
  const selectVisual = useDesignerStore((state) => state.selectVisual);
  const moveVisual = useDesignerStore((state) => state.moveVisual);
  const resizeVisual = useDesignerStore((state) => state.resizeVisual);
  const setPageFilters = useDesignerStore((state) => state.setPageFilters);
  const activePageIndex = useDesignerStore((state) => state.activePageIndex);
  const page = report.pages[activePageIndex];
  const frame = useRef<HTMLDivElement>(null);
  const offset = useRef({ dx: 0, dy: 0 });
  const dragRef = useRef<({ id: string } & Box) | null>(null);
  const resizeRef = useRef<{ id: string; handle: ResizeHandle; start: Box } | null>(null);
  const [drag, setDrag] = useState<({ id: string } & Box) | null>(null);
  const [guides, setGuides] = useState<Guide[]>([]);
  function placeDrag(next: ({ id: string } & Box) | null, lines: Guide[] = []) {
    dragRef.current = next;
    setDrag(next);
    setGuides(lines);
  }
  const grip = Math.min(18, Math.max(10, Math.round(12 / scale)));

  return (
    <div
      ref={frame}
      className="page"
      style={{ width: PAGE_WIDTH * scale, height: PAGE_HEIGHT * scale, background: report.theme?.id ? theme.surface.page : report.theme?.background }}
      onPointerDown={() => {
        if (!readOnly) selectVisual(null);
      }}
    >
    <div className="page-inner" style={{ width: PAGE_WIDTH, height: PAGE_HEIGHT, transform: `scale(${scale})` }}>
      {guides.map((guide) => (
        <div
          key={`${guide.axis}:${guide.at}`}
          className={guide.axis === "x" ? "guide vertical" : "guide horizontal"}
          style={guide.axis === "x" ? { left: guide.at } : { top: guide.at }}
        />
      ))}
      {page?.visuals.filter((visual) => !visual.properties?.hidden).map((visual) => (
        <VisualFrame
          key={visual.id}
          id={visual.id}
          selected={visual.id === selectedId}
          kit={isKitType(visual.type) || visual.properties?.box === true}
          style={{
            left: drag?.id === visual.id ? drag.x : visual.x,
            top: drag?.id === visual.id ? drag.y : visual.y,
            width: drag?.id === visual.id ? drag.width : visual.width,
            height: drag?.id === visual.id ? drag.height : visual.height,
            background: visual.properties?.bgShow ? String(visual.properties.bgColor ?? "#fff") : undefined,
            border: visual.properties?.borderShow ? `1px solid ${String(visual.properties.borderColor ?? "#E0E3E8")}` : undefined,
            borderRadius: visual.properties?.borderShow ? Number(visual.properties.borderRadius ?? 4) : undefined,
          }}
          onPointerDown={(event) => {
            event.stopPropagation();
            if (!readOnly) selectVisual(visual.id);
          }}
        >
          {!readOnly && (
          <div
            className="visual-handle"
            onPointerDown={(event) => {
              event.stopPropagation();
              selectVisual(visual.id);
              const rect = frame.current?.getBoundingClientRect();
              if (!rect) return;
              const point = pagePoint(event.clientX, event.clientY, rect.left, rect.top, scale);
              offset.current = { dx: point.x - visual.x, dy: point.y - visual.y };
              placeDrag({
                id: visual.id,
                x: visual.x,
                y: visual.y,
                width: visual.width,
                height: visual.height,
              });
              event.currentTarget.setPointerCapture(event.pointerId);
            }}
            onPointerMove={(event) => {
              if (dragRef.current?.id !== visual.id) return;
              const rect = frame.current?.getBoundingClientRect();
              if (!rect) return;
              const point = pageOffset(event.clientX, event.clientY, rect.left, rect.top, scale);
              const others = (page?.visuals ?? [])
                .filter((item) => item.id !== visual.id)
                .map((item) => ({ x: item.x, y: item.y, width: item.width, height: item.height }));
              const aligned = moveWithGuides(
                {
                  x: point.x - offset.current.dx,
                  y: point.y - offset.current.dy,
                  width: visual.width,
                  height: visual.height,
                },
                others,
              );
              placeDrag({ id: visual.id, ...aligned.box }, aligned.guides);
            }}
            onPointerUp={() => {
              const current = dragRef.current;
              if (current && current.id === visual.id) {
                moveVisual(visual.id, current.x, current.y);
              }
              placeDrag(null);
            }}
          />
          )}
          {!readOnly && selectedId === visual.id &&
            (["n", "s", "e", "w", "ne", "nw", "se", "sw"] as const).map((handle) => (
              <div
                key={handle}
                className={`resize-handle ${handle}`}
                style={{ width: grip, height: grip }}
                role="button"
                aria-label={`Resize ${handle}`}
                onPointerDown={(event) => {
                  event.stopPropagation();
                  selectVisual(visual.id);
                  resizeRef.current = {
                    id: visual.id,
                    handle,
                    start: {
                      x: visual.x,
                      y: visual.y,
                      width: visual.width,
                      height: visual.height,
                    },
                  };
                  event.currentTarget.setPointerCapture(event.pointerId);
                }}
                onPointerMove={(event) => {
                  const session = resizeRef.current;
                  if (!session || session.id !== visual.id) return;
                  const rect = frame.current?.getBoundingClientRect();
                  if (!rect) return;
                  const point = pageOffset(event.clientX, event.clientY, rect.left, rect.top, scale);
                  const others = (page?.visuals ?? [])
                    .filter((item) => item.id !== visual.id)
                    .map((item) => ({ x: item.x, y: item.y, width: item.width, height: item.height }));
                  const lines: Guide[] = [];
                  const box = resizeBox(session.start, session.handle, point.x, point.y, (value, axis) => {
                    const snapped = snapAxis(
                      value,
                      axisTargets(others, axis, axis === "x" ? PAGE_WIDTH : PAGE_HEIGHT),
                    );
                    if (snapped.guide !== null) lines.push({ axis, at: snapped.guide });
                    return snapped.value;
                  });
                  placeDrag({ id: visual.id, ...box }, lines);
                }}
                onPointerUp={() => {
                  const current = dragRef.current;
                  if (current && resizeRef.current?.id === visual.id) {
                    resizeVisual(visual.id, current);
                  }
                  resizeRef.current = null;
                  placeDrag(null);
                }}
              />
            ))}
          <div className="visual-body">
          <VisualView
            visual={visual}
            workspaceId={workspaceId}
            datasetId={datasetId}
            readOnly={readOnly}
            filters={filtersForVisual(
              [...(report.filters ?? []), ...(page?.filters ?? []), ...(visual.filters ?? [])],
              cross,
              visual.id,
              cross
                ? (page?.visuals.find((item) => item.id === cross.sourceId)?.interactions?.targets[visual.id] ?? "crossFilter") === "crossFilter"
                : true,
            )}
            highlightCategory={
              cross &&
              (page?.visuals.find((item) => item.id === cross.sourceId)?.interactions?.targets[visual.id] ?? "crossFilter") ===
                "crossHighlight"
                ? cross.value
                : undefined
            }
            onCategory={(category) => {
              const group = groupingOf(visual);
              if (!group) return;
              onCross(toggleCrossFilter(cross, visual.id, group.table, group.column, category));
            }}
            onSlicerValues={(values, filters) => {
              const group = groupingOf(visual);
              if (!group) return;
              const rest = (page?.filters ?? []).filter(
                (filter) => !(filter.table === group.table && filter.column === group.column),
              );
              if (filters) {
                setPageFilters([...rest, ...filters]);
                return;
              }
              setPageFilters(
                values.length === 0
                  ? rest
                  : [...rest, { table: group.table, column: group.column, type: "basic", config: { operator: "in", values } }],
              );
            }}
          />
          </div>
        </VisualFrame>
      ))}
    </div>
    </div>
  );
}

function VisualFrame({
  id,
  selected,
  kit = false,
  style,
  onPointerDown,
  children,
}: {
  id: string;
  selected: boolean;
  kit?: boolean;
  style: CSSProperties;
  onPointerDown: (event: PointerEvent<HTMLDivElement>) => void;
  children: ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `visual:${id}`, data: { visualId: id } });
  const base = kit ? "visual kit" : "visual";
  const tone = selected ? `${base} selected` : base;
  return (
    <div ref={setNodeRef} className={isOver ? `${tone} over` : tone} style={style} onPointerDown={onPointerDown}>
      {children}
    </div>
  );
}
