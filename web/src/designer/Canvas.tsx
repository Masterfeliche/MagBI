/** Free-form page. Positions are page pixels; pointer deltas are divided by the CSS scale. */

import { useRef, useState } from "react";

import { PAGE_HEIGHT, PAGE_WIDTH, pagePoint } from "./layout";
import { useDesignerStore } from "./store";

export function Canvas({ scale }: { scale: number }) {
  const report = useDesignerStore((state) => state.report);
  const selectedId = useDesignerStore((state) => state.selectedVisualId);
  const selectVisual = useDesignerStore((state) => state.selectVisual);
  const moveVisual = useDesignerStore((state) => state.moveVisual);
  const page = report.pages[0];
  const frame = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ id: string; dx: number; dy: number } | null>(null);

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
            left: visual.x,
            top: visual.y,
            width: visual.width,
            height: visual.height,
          }}
          onPointerDown={(event) => {
            event.stopPropagation();
            selectVisual(visual.id);
            const rect = frame.current?.getBoundingClientRect();
            if (!rect) return;
            const point = pagePoint(event.clientX, event.clientY, rect.left, rect.top, scale);
            setDrag({ id: visual.id, dx: point.x - visual.x, dy: point.y - visual.y });
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            if (!drag || drag.id !== visual.id) return;
            const rect = frame.current?.getBoundingClientRect();
            if (!rect) return;
            const point = pagePoint(event.clientX, event.clientY, rect.left, rect.top, scale);
            moveVisual(visual.id, point.x - drag.dx, point.y - drag.dy);
          }}
          onPointerUp={() => setDrag(null)}
        >
          <span className="visual-label">{visual.type}</span>
        </div>
      ))}
    </div>
  );
}
