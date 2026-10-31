import { useEffect, useMemo, useState } from "react";

import { apiFetch } from "../shared/api";
import { builtInTheme, BUILT_IN_THEMES, resolveTheme, SAVED_PREFIX, type MagbiTheme, type ThemeLayer } from "../shared/theme";
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

type Target = "report" | "workspace" | "organisation";

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

/**
 * "Customize current theme": change colours, type and shape, see the result and
 * every check it fails, then keep it on this report or save it for the
 * workspace (editors) or the organisation (platform admins). Under a locked
 * organisation theme only the chart colours can change.
 */
export function ThemeDialog({
  baseId,
  resolved,
  locked,
  workspaceId,
  onSaveReport,
  onShared,
  onClose,
}: {
  baseId: string;
  resolved: MagbiTheme;
  locked?: string;
  workspaceId?: string;
  onSaveReport: (theme: ThemeOverrides) => void;
  onShared: (themeId: string) => void;
  onClose: () => void;
}) {
  const [base, setBase] = useState(baseId);
  const [draft, setDraft] = useState<MagbiTheme>(resolved);
  const [target, setTarget] = useState<Target>("report");
  const [name, setName] = useState("");
  const [makeDefault, setMakeDefault] = useState(false);
  const [lock, setLock] = useState(false);
  const [admin, setAdmin] = useState(false);
  const [refused, setRefused] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const problems = useMemo(() => themeProblems(draft), [draft]);
  const edit = (layer: ThemeLayer) => setDraft((theme) => resolveTheme(theme, [layer]));
  const colours = draft.data.categorical;
  const frozen = Boolean(locked);

  useEffect(() => {
    apiFetch<{ platformAdmin?: boolean }>("/auth/whoami")
      .then((who) => setAdmin(Boolean(who.platformAdmin)))
      .catch(() => setAdmin(false));
  }, []);

  async function save() {
    setRefused([]);
    if (target === "report") {
      onSaveReport(frozen ? { overrides: { data: { categorical: colours } } } : { id: base, overrides: layerOf(draft) });
      onClose();
      return;
    }
    const path = target === "organisation" ? "/organisation/themes" : `/workspaces/${workspaceId}/themes`;
    setSaving(true);
    try {
      const saved = await apiFetch<{ id: string }>(path, {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          definition: { extends: base, ...layerOf(draft) },
          isDefault: makeDefault,
          locked: target === "organisation" && makeDefault && lock,
        }),
      });
      onShared(`${SAVED_PREFIX}${saved.id}`);
      onClose();
    } catch (reason) {
      const [message, ...failed] = (reason instanceof Error ? reason.message : "The theme was not saved.").split("\n");
      setRefused(failed.length ? failed : [message]);
    } finally {
      setSaving(false);
    }
  }

  const blocked = problems.length > 0 || saving || (target !== "report" && name.trim() === "");

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal theme-dialog" role="dialog" aria-label="Customize theme" onClick={(event) => event.stopPropagation()}>
        <h3>Customize theme</h3>
        {frozen && (
          <p className="theme-locked" role="status">
            ● Your organisation has locked its theme, <b>{locked}</b>. Only the chart colours of this report can change.
          </p>
        )}
        <div className="theme-dialog-body">
          <div className="theme-dialog-form">
            <fieldset className="theme-fieldset" disabled={frozen}>
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
            </fieldset>

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

            <fieldset className="theme-fieldset" disabled={frozen}>
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
            </fieldset>

            {!frozen && (
              <>
                <h4>Save for</h4>
                <div className="theme-targets" role="radiogroup" aria-label="Save for">
                  <label className="theme-check">
                    <input type="radio" name="target" checked={target === "report"} onChange={() => setTarget("report")} />
                    This report only
                  </label>
                  {workspaceId && (
                    <label className="theme-check">
                      <input type="radio" name="target" checked={target === "workspace"} onChange={() => setTarget("workspace")} />
                      Everyone in this workspace (a workspace theme)
                    </label>
                  )}
                  {admin && (
                    <label className="theme-check">
                      <input type="radio" name="target" checked={target === "organisation"} onChange={() => setTarget("organisation")} />
                      The whole organisation (an organisation theme)
                    </label>
                  )}
                </div>
                {target !== "report" && (
                  <>
                    <label className="theme-field">
                      <span>Theme name</span>
                      <input type="text" value={name} maxLength={200} onChange={(event) => setName(event.target.value)} />
                    </label>
                    <label className="theme-check">
                      <input type="checkbox" checked={makeDefault} onChange={(event) => setMakeDefault(event.target.checked)} />
                      Use for every report that has not picked a theme
                    </label>
                    {target === "organisation" && (
                      <label className="theme-check">
                        <input type="checkbox" checked={lock && makeDefault} disabled={!makeDefault} onChange={(event) => setLock(event.target.checked)} />
                        Lock it: reports keep this theme and may change chart colours only
                      </label>
                    )}
                  </>
                )}
              </>
            )}
          </div>

          <div className="theme-dialog-side">
            <ThemePreview theme={draft} />
            {problems.length === 0 && refused.length === 0 ? (
              <p className="theme-ok">▲ Passes every readability and colour check.</p>
            ) : (
              <div className="theme-problems" role="alert">
                <p>▼ {refused.length ? "The theme was not saved:" : "Fix these before saving:"}</p>
                <ul>
                  {[...problems, ...refused].map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
        <div className="theme-actions">
          <button type="button" className="ws-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="ws-btn primary" disabled={blocked} onClick={() => void save()}>
            {saving ? "Saving…" : "Save theme"}
          </button>
        </div>
      </div>
    </div>
  );
}
