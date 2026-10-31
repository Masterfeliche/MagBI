import { BUILT_IN_THEMES, lockedTheme, savedTheme, type MagbiTheme, type SavedThemes } from "../shared/theme";

/** A small picture of a theme: page, a KPI card in each status, and the chart colours. */
export function ThemePreview({ theme }: { theme: MagbiTheme }) {
  const tones = ["good", "watch", "action"] as const;
  return (
    <div className="theme-preview" style={{ background: theme.surface.page, fontFamily: theme.type.family, borderRadius: theme.shape.radius }}>
      <div className="theme-preview-cards">
        {tones.map((tone) => (
          <div
            key={tone}
            className="theme-preview-card"
            style={{ background: theme.surface.frame, borderColor: theme.surface.line, borderLeftColor: theme.status[tone].color, borderRadius: theme.shape.radius / 2 }}
          >
            <b style={{ color: theme.text.ink }}>12</b>
            <i style={{ color: theme.status[tone].ink }}>{theme.status[tone].glyph}</i>
          </div>
        ))}
      </div>
      <div className="theme-preview-panel" style={{ background: theme.surface.panel, borderColor: theme.surface.line, borderRadius: theme.shape.radius / 2 }}>
        {theme.data.categorical.slice(0, 5).map((colour, index) => (
          <span key={colour} style={{ background: colour, width: `${88 - index * 14}%` }} />
        ))}
      </div>
    </div>
  );
}

function Tiles({ themes, current, disabled, onPick }: { themes: MagbiTheme[]; current: string; disabled: boolean; onPick: (id: string) => void }) {
  return (
    <div className="theme-grid">
      {themes.map((theme) => (
        <button
          key={theme.id}
          type="button"
          className={theme.id === current ? "theme-tile on" : "theme-tile"}
          aria-pressed={theme.id === current}
          title={theme.description}
          disabled={disabled}
          onClick={() => onPick(theme.id)}
        >
          <ThemePreview theme={theme} />
          <span className="theme-tile-name">{theme.name}</span>
          <span className="theme-tile-desc">{theme.description}</span>
        </button>
      ))}
    </div>
  );
}

/**
 * The themes a report may use, each drawn with its own colours: the
 * organisation's, this workspace's, then the built-in ones. Picking one
 * restyles the whole report. A locked organisation theme cannot be changed here.
 */
export function ThemeGallery({ current, saved, onPick, onClose }: { current: string; saved: SavedThemes; onPick: (id: string) => void; onClose: () => void }) {
  const locked = lockedTheme(saved);
  const sections = [
    { title: "Your organisation", themes: saved.organisation.map(savedTheme) },
    { title: "This workspace", themes: saved.workspace.map(savedTheme) },
    { title: "Built-in", themes: BUILT_IN_THEMES },
  ].filter((section) => section.themes.length > 0);
  const shown = locked ? savedTheme(locked).id : current;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal theme-gallery" role="dialog" aria-label="Themes" onClick={(event) => event.stopPropagation()}>
        <h3>Themes</h3>
        {locked && (
          <p className="theme-locked" role="status">
            ● Your organisation has locked its theme, <b>{locked.name}</b>. Reports keep it; you can still change chart colours in Customize.
          </p>
        )}
        {sections.map((section) => (
          <section key={section.title} className="theme-section">
            {sections.length > 1 && <h4>{section.title}</h4>}
            <Tiles themes={section.themes} current={shown} disabled={Boolean(locked)} onPick={onPick} />
          </section>
        ))}
        <div className="theme-actions">
          <button type="button" className="ws-btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
