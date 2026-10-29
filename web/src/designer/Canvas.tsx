/** Free-form page. Positions are page pixels; pointer deltas are divided by the CSS scale. */

import { useRef, useState } from "react";

import { VisualView } from "./Charts";
import { filtersForVisual, groupingOf, toggleCrossFilter, type CrossFilter } from "./filters";
import {
  PAGE_HEIGHT,
  PAGE_WIDTH,
  clampPosition,
  pageOffset,
  pagePoint,
  resizeBox,
  type Box,
  type ResizeHandle,
} from "./layout";
import { useDesignerStore } from "./store";

export function Canvas({
  scale,
  workspaceId,
  datasetId,
  cross,
  onCross,
}: {
  scale: number;
  workspaceId: string;
  datasetId: string;
  cross: CrossFilter | null;
  onCross: (next: CrossFilter | null) => void;
}) {
  const report = useDesignerStore((state) => state.report);
  const selectedId = useDesignerStore((state) => state.selectedVisualId);
  const selectVisual = useDesignerStore((state) => state.selectVisual);
  const moveVisual = useDesignerStore((state) => state.moveVisual);
  const resizeVisual = useDesignerStore((state) => state.resizeVisual);
  const setPageFilters = useDesignerStore((state) => state.setPageFilters);
  const page = report.pages[0];
  const frame = useRef<HTMLDivElement>(null);
  const offset = useRef({ dx: 0, dy: 0 });
  const dragRef = useRef<({ id: string } & Box) | null>(null);
  const resizeRef = useRef<{ id: string; handle: ResizeHandle; start: Box } | null>(null);
  const [drag, setDrag] = useState<({ id: string } & Box) | null>(null);
  function placeDrag(next: ({ id: string } & Box) | null) {
    dragRef.current = next;
    setDrag(next);
  }
  const grip = Math.min(18, Math.max(10, Math.round(12 / scale)));

  return (
    <div
      ref={frame}
      className="page"
      style={{ width: PAGE_WIDTH, height: PAGE_HEIGHT, transform: `scale(${scale})` }}
      onPointerDown={() => selectVisual(null)}
    >
      {page?.visuals.map((visual) => (
        <div
          key={visual.id}
          className={visual.id === selectedId ? "visual selected" : "visual"}
          style={{
            left: drag?.id === visual.id ? drag.x : visual.x,
            top: drag?.id === visual.id ? drag.y : visual.y,
            width: drag?.id === visual.id ? drag.width : visual.width,
            height: drag?.id === visual.id ? drag.height : visual.height,
          }}
          onPointerDown={(event) => {
            event.stopPropagation();
            selectVisual(visual.id);
          }}
        >
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
              const point = pagePoint(event.clientX, event.clientY, rect.left, rect.top, scale);
              const clamped = clampPosition(
                point.x - offset.current.dx,
                point.y - offset.current.dy,
                visual.width,
                visual.height,
              );
              placeDrag({ id: visual.id, ...clamped, width: visual.width, height: visual.height });
            }}
            onPointerUp={() => {
              const current = dragRef.current;
              if (current && current.id === visual.id) {
                moveVisual(visual.id, current.x, current.y);
              }
              placeDrag(null);
            }}
          />
          {selectedId === visual.id &&
            (["n", "s", "e", "w", "ne", "nw", "se", "sw"] as const).map((handle) => (
              <div
                key={handle}
                className={`resize-handle ${handle}`}
                style={{ width: grip, height: grip }}
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
                  placeDrag({ id: visual.id, ...resizeBox(session.start, session.handle, point.x, point.y) });
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
            filters={filtersForVisual(page?.filters ?? [], cross, visual.id)}
            onCategory={(category) => {
              const group = groupingOf(visual);
              if (!group) return;
              onCross(toggleCrossFilter(cross, visual.id, group.table, group.column, category));
            }}
            onSlicer={(value) => {
              const group = groupingOf(visual);
              if (!group) return;
              setPageFilters([
                ...(page?.filters ?? []),
                {
                  table: group.table,
                  column: group.column,
                  type: "basic",
                  config: { operator: "eq", values: [value] },
                },
              ]);
            }}
          />
          </div>
        </div>
      ))}
    </div>
  );
}
