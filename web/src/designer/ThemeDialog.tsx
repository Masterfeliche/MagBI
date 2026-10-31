import { useMemo, useState } from "react";

import { builtInTheme, BUILT_IN_THEMES, resolveTheme, type MagbiTheme, type ThemeLayer } from "../shared/theme";
import { themeProblems } from "../shared/themeCheck";
import type { ThemeOverrides } from "../types/report";
import { ThemePreview } from "./ThemeGallery";

const FONTS = [
  { label: "Segoe UI", value: "\"Segoe UI\", \"IBM Plex Sans\", system-ui, sans-serif" },
  { label: "IBM Plex Sans", value: "\"IBM Plex Sans\", \"Segoe UI\", system-ui, sans-serif" },
  { label: "Arial", value: "Arial, Helvetica, sans-serif" },
  { label: "Verdana", value: "Verdana, Geneva, sans-serif" },
  { label: "Georgia", value: "Georgia, \"Times New Roman\", serif" },
];
const SCALES = [1, 1.1, 1.15, 1.2];

/** The parts of a theme this dialog edits, as a layer over the base theme. */
function layerOf(theme: MagbiTheme): ThemeLayer {
  return {
    surface: { page: theme.surface.page, panel: theme.surface.panel, strip: theme.surface.strip, line: theme.surface.line },
    text: { ink: theme.text.ink, muted: theme.text.muted },
    data: { style: theme.data.style, categorical: theme.data.categorical },
    status: { good: { color: theme.status.good.color }, watch: { color: theme.status.watch.color }, action: { color: theme.status.action.color } },
    type: { family: theme.type.family, scale: theme.type.scale },
    shape: { radius: theme.shape.radius },
    chart: { gridlines: theme.chart.gridlines },
    pattern: theme.pattern,
  };
}

function Swatch({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="theme-field">
      <span>{label}</span>
      <input type="color" value={value} onChange={(event) => onChange(event.target.value.toUpperCase())} />
      <code>{value}</code>
    </label>
  );
}

/** "Customize current theme": change colours, type and shape, see the result and every check it fails. */
export function ThemeDialog({ current, resolved, onSave, onClose }: { current: string; resolved: MagbiTheme; onSave: (theme: ThemeOverrides) => void; onClose: () => void }) {
  const [base, setBase] = useState(current);
  const [draft, setDraft] = useState<MagbiTheme>(resolved);
  const problems = useMemo(() => themeProblems(draft), [draft]);
  const edit = (layer: ThemeLayer) => setDraft((theme) => resolveTheme(theme, [layer]));
  const colours = draft.data.categorical;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal theme-dialog" role="dialog" aria-label="Customize theme" onClick={(event) => event.stopPropagation()}>
        <h3>Customize theme</h3>
        <div className="theme-dialog-body">
          <div className="theme-dialog-form">
            <label className="theme-field">
              <span>Start from</span>
              <select
                value={base}
                onChange={(event) => {
                  setBase(event.target.value);
                  setDraft(builtInTheme(event.target.value));
                }}
              >
                {BUILT_IN_THEMES.map((theme) => (
                  <option key={theme.id} value={theme.id}>{theme.name}</option>
                ))}
              </select>
            </label>

            <h4>Page and panels</h4>
            <Swatch label="Page" value={draft.surface.page} onChange={(page) => edit({ surface: { page } })} />
            <Swatch label="Panels" value={draft.surface.panel} onChange={(panel) => edit({ surface: { panel } })} />
            <Swatch label="Panel headers" value={draft.surface.strip} onChange={(strip) => edit({ surface: { strip } })} />
            <Swatch label="Lines" value={draft.surface.line} onChange={(line) => edit({ surface: { line } })} />

            <h4>Text</h4>
            <Swatch label="Text" value={draft.text.ink} onChange={(ink) => edit({ text: { ink } })} />
            <Swatch label="Muted text" value={draft.text.muted} onChange={(muted) => edit({ text: { muted } })} />
            <label className="theme-field">
              <span>Font</span>
              <select value={FONTS.find((font) => font.value === draft.type.family)?.value ?? draft.type.family} onChange={(event) => edit({ type: { family: event.target.value } })}>
                {!FONTS.some((font) => font.value === draft.type.family) && <option value={draft.type.family}>{draft.type.family}</option>}
                {FONTS.map((font) => (
                  <option key={font.label} value={font.value}>{font.label}</option>
                ))}
              </select>
            </label>
            <label className="theme-field">
              <span>Text size</span>
              <select value={draft.type.scale} onChange={(event) => edit({ type: { scale: Number(event.target.value) } })}>
                {SCALES.map((scale) => (
                  <option key={scale} value={scale}>{Math.round(scale * 100)}%</option>
                ))}
              </select>
            </label>

            <h4>Chart colours</h4>
            {colours.map((colour, index) => (
              <div key={index} className="theme-row">
                <Swatch
                  label={`Colour ${index + 1}`}
                  value={colour}
                  onChange={(value) => edit({ data: { categorical: colours.map((item, at) => (at === index ? value : item)) } })}
                />
                {colours.length > 1 && (
                  <button type="button" className="ws-btn" aria-label={`Remove colour ${index + 1}`} onClick={() => edit({ data: { categorical: colours.filter((_, at) => at !== index) } })}>
                    Remove
                  </button>
                )}
              </div>
            ))}
            {colours.length < 8 && (
              <button type="button" className="ws-btn" onClick={() => edit({ data: { categorical: [...colours, "#7F7F7F"] } })}>Add colour</button>
            )}
            <label className="theme-check">
              <input type="checkbox" checked={draft.data.style === "ramp"} onChange={(event) => edit({ data: { style: event.target.checked ? "ramp" : "categorical" } })} />
              One colour in light-to-dark steps (charts always labelled)
            </label>

            <h4>Status</h4>
            <Swatch label={draft.status.good.word} value={draft.status.good.color} onChange={(color) => edit({ status: { good: { color } } })} />
            <Swatch label={draft.status.watch.word} value={draft.status.watch.color} onChange={(color) => edit({ status: { watch: { color } } })} />
            <Swatch label={draft.status.action.word} value={draft.status.action.color} onChange={(color) => edit({ status: { action: { color } } })} />

            <h4>Shape</h4>
            <label className="theme-field">
              <span>Corners</span>
              <input type="number" min={0} max={16} value={draft.shape.radius} onChange={(event) => edit({ shape: { radius: Math.max(0, Math.min(16, Number(event.target.value) || 0)) } })} />
            </label>
            <label className="theme-check">
              <input type="checkbox" checked={draft.chart.gridlines} onChange={(event) => edit({ chart: { gridlines: event.target.checked } })} />
              Gridlines on charts
            </label>
            <label className="theme-check">
              <input type="checkbox" checked={draft.pattern} onChange={(event) => edit({ pattern: event.target.checked })} />
              Patterns on chart series as well as colour
            </label>
          </div>

          <div className="theme-dialog-side">
            <ThemePreview theme={draft} />
            {problems.length === 0 ? (
              <p className="theme-ok">▲ Passes every readability and colour check.</p>
            ) : (
              <div className="theme-problems" role="alert">
                <p>▼ Fix these before saving:</p>
                <ul>
                  {problems.map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
        <div className="theme-actions">
          <button type="button" className="ws-btn" onClick={onClose}>Cancel</button>
          <button
            type="button"
            className="ws-btn primary"
            disabled={problems.length > 0}
            onClick={() => {
              onSave({ id: base, overrides: layerOf(draft) });
              onClose();
            }}
          >
            Save theme
          </button>
        </div>
      </div>
    </div>
  );
}
