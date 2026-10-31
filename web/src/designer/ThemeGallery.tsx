import { BUILT_IN_THEMES, type MagbiTheme } from "../shared/theme";

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

/** The built-in themes, each drawn with its own colours; picking one restyles the whole report. */
export function ThemeGallery({ current, onPick, onClose }: { current: string; onPick: (id: string) => void; onClose: () => void }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal theme-gallery" role="dialog" aria-label="Themes" onClick={(event) => event.stopPropagation()}>
        <h3>Themes</h3>
        <div className="theme-grid">
          {BUILT_IN_THEMES.map((theme) => (
            <button
              key={theme.id}
              type="button"
              className={theme.id === current ? "theme-tile on" : "theme-tile"}
              aria-pressed={theme.id === current}
              title={theme.description}
              onClick={() => onPick(theme.id)}
            >
              <ThemePreview theme={theme} />
              <span className="theme-tile-name">{theme.name}</span>
              <span className="theme-tile-desc">{theme.description}</span>
            </button>
          ))}
        </div>
        <div className="theme-actions">
          <button type="button" className="ws-btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
