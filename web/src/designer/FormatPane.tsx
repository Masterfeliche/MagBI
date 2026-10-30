import { useState } from "react";

import { useDesignerStore } from "./store";

interface FormatGroup {
  label: string;
  rows: FormatRow[];
}

type FormatRow =
  | { type: "toggle"; label: string; key: string; default: boolean }
  | { type: "input"; label: string; key: string; default: string }
  | { type: "number"; label: string; key: string; default: number }
  | { type: "color"; label: string; key: string; default: string }
  | { type: "select"; label: string; key: string; default: string; options: string[] };

const FORMAT_GROUPS: FormatGroup[] = [
  {
    label: "General",
    rows: [
      { type: "number", label: "Width", key: "width", default: 360 },
      { type: "number", label: "Height", key: "height", default: 240 },
      { type: "number", label: "X position", key: "x", default: 0 },
      { type: "number", label: "Y position", key: "y", default: 0 },
      { type: "toggle", label: "Lock aspect", key: "lockAspect", default: false },
    ],
  },
  {
    label: "Title",
    rows: [
      { type: "toggle", label: "Show", key: "titleShow", default: true },
      { type: "input", label: "Text", key: "title", default: "" },
      { type: "number", label: "Font size", key: "titleFontSize", default: 14 },
      { type: "color", label: "Color", key: "titleColor", default: "#1E293B" },
      { type: "select", label: "Alignment", key: "titleAlign", default: "Left", options: ["Left", "Center", "Right"] },
    ],
  },
  {
    label: "X-axis",
    rows: [
      { type: "toggle", label: "Show", key: "xShow", default: true },
      { type: "number", label: "Font size", key: "xFontSize", default: 10 },
      { type: "color", label: "Color", key: "xColor", default: "#64748B" },
    ],
  },
  {
    label: "Y-axis",
    rows: [
      { type: "toggle", label: "Show", key: "yShow", default: true },
      { type: "select", label: "Display units", key: "yUnits", default: "Auto", options: ["Auto", "None", "K", "M"] },
    ],
  },
  {
    label: "Data colors",
    rows: [
      { type: "color", label: "Series 1", key: "color", default: "#2B5797" },
      { type: "color", label: "Series 2", key: "color2", default: "#3A7BD5" },
    ],
  },
  {
    label: "Data labels",
    rows: [
      { type: "toggle", label: "Show", key: "labelsShow", default: false },
      { type: "select", label: "Position", key: "labelsPos", default: "Outside end", options: ["Outside end", "Inside end", "Center"] },
    ],
  },
  {
    label: "Legend",
    rows: [
      { type: "toggle", label: "Show", key: "legendShow", default: true },
      { type: "select", label: "Position", key: "legendPos", default: "Top", options: ["Top", "Bottom", "Left", "Right"] },
    ],
  },
  {
    label: "Background",
    rows: [
      { type: "toggle", label: "Show", key: "bgShow", default: false },
      { type: "color", label: "Color", key: "bgColor", default: "#FFFFFF" },
      { type: "number", label: "Transparency %", key: "bgTransparency", default: 0 },
    ],
  },
  {
    label: "Border",
    rows: [
      { type: "toggle", label: "Show", key: "borderShow", default: false },
      { type: "color", label: "Color", key: "borderColor", default: "#E0E3E8" },
      { type: "number", label: "Radius", key: "borderRadius", default: 4 },
    ],
  },
];

export function FormatPane() {
  const selectedId = useDesignerStore((s) => s.selectedVisualId);
  const report = useDesignerStore((s) => s.report);
  const activePageIndex = useDesignerStore((s) => s.activePageIndex);
  const setProperties = useDesignerStore((s) => s.setProperties);
  const resizeVisual = useDesignerStore((s) => s.resizeVisual);
  const moveVisual = useDesignerStore((s) => s.moveVisual);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const page = report.pages[activePageIndex];
  const visual = page?.visuals.find((v) => v.id === selectedId);

  if (!visual) {
    return <div className="format-section"><p className="hint">Select a visual to format.</p></div>;
  }

  const props = visual.properties ?? {};

  function getValue(row: FormatRow): unknown {
    if (!visual) return row.default;
    if (row.key === "width") return visual.width;
    if (row.key === "height") return visual.height;
    if (row.key === "x") return visual.x;
    if (row.key === "y") return visual.y;
    return props[row.key] ?? row.default;
  }

  function onChange(key: string, value: unknown) {
    if (!visual) return;
    if (key === "width" || key === "height") {
      resizeVisual(visual.id, {
        x: visual.x, y: visual.y,
        width: key === "width" ? Number(value) || visual.width : visual.width,
        height: key === "height" ? Number(value) || visual.height : visual.height,
      });
    } else if (key === "x" || key === "y") {
      moveVisual(visual.id,
        key === "x" ? Number(value) || 0 : visual.x,
        key === "y" ? Number(value) || 0 : visual.y,
      );
    } else {
      setProperties(visual.id, { [key]: value });
    }
  }

  return (
    <div className="format-section">
      {FORMAT_GROUPS.map((group) => {
        const isOpen = !collapsed[group.label];
        return (
          <div key={group.label} className="fmt-group">
            <button
              type="button"
              className="fmt-group-header"
              onClick={() => setCollapsed((s) => ({ ...s, [group.label]: !s[group.label] }))}
            >
              {group.label}
              <span>{isOpen ? "▾" : "▸"}</span>
            </button>
            {isOpen && group.rows.map((row) => {
              const val = getValue(row);
              return (
                <div key={row.key} className="fmt-row">
                  <label>{row.label}</label>
                  {row.type === "toggle" && (
                    <button
                      type="button"
                      className={`fmt-toggle${val ? " on" : ""}`}
                      onClick={() => onChange(row.key, !val)}
                    />
                  )}
                  {row.type === "input" && (
                    <input
                      className="fmt-input"
                      value={String(val)}
                      onChange={(e) => onChange(row.key, e.target.value)}
                    />
                  )}
                  {row.type === "number" && (
                    <input
                      className="fmt-input"
                      type="number"
                      value={Number(val)}
                      onChange={(e) => onChange(row.key, Number(e.target.value))}
                    />
                  )}
                  {row.type === "color" && (
                    <input
                      type="color"
                      className="fmt-color"
                      value={String(val)}
                      onChange={(e) => onChange(row.key, e.target.value)}
                    />
                  )}
                  {row.type === "select" && (
                    <select
                      className="fmt-select"
                      value={String(val)}
                      onChange={(e) => onChange(row.key, e.target.value)}
                    >
                      {row.options.map((opt) => <option key={opt}>{opt}</option>)}
                    </select>
                  )}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
