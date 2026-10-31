# Feature: MAGBI-018 - Theme system for different use cases

MagBI is a product used by many organisations, so a "theme" has to be more than a chart palette. Each customer needs its own brand, each industry and kind of screen (desk, phone, projector, embedded in another app) needs a different treatment, and some people need an accessible version. None of these may break the status meanings (good, watch, action, no data).

## 1. Analysis

### 1.1 What MagBI has today (31 Oct 2026)

| Area | Today | Where |
|------|-------|-------|
| Report theme | `ThemeOverrides { colors, font, background }`. Only `colors` and `background` are used; `font` is stored but never read | `web/src/types/report.ts`, `designer/Charts.tsx`, `designer/Canvas.tsx` |
| Presets | 3 palettes: ERP Native, Default (Power BI blue) and MSD Enterprise. The ribbon only offers "MSD theme" and "Default theme", so ERP Native, the real standard, can't be picked | `shared/themes.ts`, `designer/Ribbon.tsx:158` |
| Theme JSON import | Reads only `dataColors` from a Power BI theme file; everything else is dropped | `colorsFromThemeJson` in `shared/themes.ts` |
| ECharts theme | `buildEChartsTheme` is a stub that returns `{}` | `shared/theme.ts` |
| Kit visuals (KPI, chain, donut, Pareto and others) | Colours, status colours and fonts are hard-coded constants (`TOKENS`, `STATUS`); `kit.css` has 37 literal hex colours and no CSS variables. These visuals ignore the report theme entirely | `kit/tone.ts`, `kit/KitVisual.tsx`, `kit/kit.css` |
| Same tokens duplicated | ERP Native is written out 4 times: `kit/tone.ts`, `designer/standard.ts`, `scripts/magbi_lib.py`, and the QA gate's allowed-colour list | |
| Frames and labels | Store literal hex in their properties (`fill: "#F8FAFC"`), so a theme change can't restyle them | `magbi_lib.Page.frame`, `KitVisual.tsx:240` |
| App chrome (designer) | Already uses CSS variables (157 uses), so it's ready for theming | `designer/designer.css` |
| Server | Doesn't know about themes: no theme table, no organisation or workspace default | |
| Embed SDK | No theme option; the host app can't pass its brand or a dark mode | `embed/sdk.ts` |
| Dark mode, high contrast, print | None | |

**In short:** a MagBI "theme" today is a list of chart colours. The look of the standard dashboards (page, panels, type, status) is fixed in code and copied across four places. A second look therefore needs those places de-hard-coded first.

### 1.2 How Power BI does it, and where MagBI should go further

| Power BI | MagBI target |
|----------|--------------|
| Report theme JSON: `dataColors`, `good/neutral/bad`, `background/foreground`, `textClasses`, `visualStyles` | The same file format can be imported and exported, so customers can bring their Power BI themes. MagBI's own schema is a superset of it |
| Built-in gallery plus "Customize current theme" | The same, plus previews drawn from the user's own report |
| A theme is set per report only; organisations rely on templates | Themes inherit across **organisation → workspace → report → visual**, and an organisation can lock its brand |
| Accessibility: a few high-contrast themes; reports aren't otherwise checked | Every theme passes a validator for contrast, colour-blind separation and distinct statuses before anyone can save it |
| Status colour is set separately on each visual | Status is a theme token with colour, ink, glyph and word, so it stays consistent everywhere and is never colour alone |
| The embedding app can't restyle a report | The embed SDK accepts a theme id or token overrides, so the ERP or other host app supplies its brand |

### 1.3 Use cases a theme must serve

Built-in list agreed on 31 Oct 2026: Enterprise Light, Classic, four industry themes, Mobile, Presentation and High Contrast. Executive, Compact, Control Room (dark) and Print were dropped.

| Use case | Who | What the theme must do | Built-in theme |
|----------|-----|------------------------|----------------|
| Daily operational dashboards | Managers and officers at a desk | Calm, light, dense enough, status at a glance | **Enterprise Light** (today's ERP Native, the default) |
| Migrating from Power BI | New customers | Looks familiar on day one | **Classic** (Power BI default palette) |
| Health and medical supply | Hospitals, medical stores, labs | Clinical teal and blue palette, calm, clean surfaces | **Health** |
| Finance and banking | Banks, finance teams, auditors | Navy and slate palette, tabular figures, restrained | **Finance** |
| Government and public sector | Ministries, agencies, parastatals | Neutral, formal, accessible contrast by default | **Government** |
| Retail and distribution | Shops, distributors, sales teams | Warmer, livelier palette, bold headline numbers | **Retail** |
| Phone viewing | Managers on the move | Larger type and touch targets (at least 44 px), wider spacing, no hover-only details | **Mobile** |
| Projectors and meeting rooms | Presenters | Very large type, strong contrast, no fine gridlines | **Presentation** |
| Accessibility | Low-vision and colour-blind users, public-sector requirements | WCAG AAA text (7:1), colour-blind-safe palette, patterns as well as colour, thicker lines and focus outlines | **High Contrast** |
| Customer brand | Each organisation (e.g. MSD) | Their colours and logo on top of a base theme, optionally locked | Organisation theme |
| Embedded in another product | ERP and other host apps | Matches the host's chrome | Set through the SDK |

Industry themes change palette, surfaces and type only. Status keeps its meaning in every theme (good, watch, action, no data, info), and its colour always comes with the glyph and word.

The Mobile theme changes type, spacing and touch sizes. It does not reflow a 1760 x 990 page into one column; that needs a separate phone-layout feature (Power BI's "mobile layout"), which is not in this plan.

Customer brands don't belong in the product's built-in list. "MSD Enterprise" moves out of `THEMES` and becomes MSD's organisation theme, locked to light, which keeps MSD's no-dark-mode decision.

### 1.4 Proposed design

**A theme is a set of tokens, not a palette.** The schema is `magbi.theme/1`, a superset of Power BI's file format:

```jsonc
{
  "$schema": "magbi.theme/1", "id": "enterprise-light", "name": "Enterprise Light",
  "extends": null, "mode": "light",
  "surface": { "page": "#EEF2F7", "panel": "#FFFFFF", "strip": "#E9EEF5", "frame": "#F8FAFC",
               "line": "#D3DCE6", "grid": "#E2E8EF", "zero": "#F3F6FA" },
  "text":    { "ink": "#22324A", "muted": "#66758A", "caption": "#5A6A80", "accent": "#2C4F80" },
  "data":    { "categorical": ["#3F6FB0", "#5F8BC9", "#82A6D6", "#B3C3D8", "..."],
               "sequential": ["#DCE8F6", "#3F6FB0"], "diverging": ["#C76E6C", "#E9EDF2", "#3F6FB0"] },
  "status":  { "good":   { "color": "#4E9E77", "ink": "#2F7354", "soft": "#DCEFE5", "glyph": "▲", "word": "On track" },
               "watch":  { "...": "..." }, "action": { "...": "..." }, "none": { "...": "..." }, "info": { "...": "..." } },
  "type":    { "family": "Segoe UI, IBM Plex Sans, sans-serif", "title": 15, "kpi": 30, "body": 12, "axis": 11 },
  "shape":   { "radius": 6, "border": 1, "shadow": "none", "density": "comfortable" },
  "pattern": false,
  "visualStyles": { }
}
```

**Resolving a theme.** Themes are merged in this order, with later ones winning: built-in base → organisation → workspace → report → the visual's own overrides. A theme marked `locked` at organisation level drops the layers below it, except for `data.categorical`.

**Rendering.** The resolved theme becomes:
- CSS custom properties (`--mb-page`, `--mb-ink`, `--mb-status-good` and so on) on the report root;
- an ECharts theme registered with `echarts.registerTheme`, which fills in the `buildEChartsTheme` stub;
- a React context that the kit reads in place of the `TOKENS` and `STATUS` constants.

Frames and labels store a token name (`fill: "frame"`) instead of a hex; a raw hex is still allowed as an explicit override.

**One source of truth.** The built-in themes live once, as JSON in `server/magbi/themes/`. They are served at `GET /api/v1/themes` and read by `magbi_lib.py` and the QA gate. The four duplicated copies go away.

**Governance.** A validator rejects a theme if:
- any text-on-surface pair has contrast below 4.5:1 (7:1 for Presentation and High Contrast);
- two neighbouring categorical colours are too close for colour-blind users;
- two statuses aren't distinct;
- a token is missing.

The QA gate checks a report against its resolved theme, not a fixed hex list.

**Viewer and embed.**
- The viewer opens Mobile automatically on a phone-width screen, unless the report's organisation theme is locked.
- Any reader can switch a report to High Contrast, a personal setting stored per user. It applies even when the organisation theme is locked, because an accessibility need outranks branding.
- `embed/sdk.ts` gains `theme: { id?, overrides? }`; anything a locked organisation theme forbids is ignored.

**Affected files**:
- Web: `shared/themes.ts`, `shared/theme.ts`, `types/report.ts`, `kit/tone.ts`, `kit/KitVisual.tsx`, `kit/kit.css`, `designer/standard.ts`, `designer/Charts.tsx`, `designer/Canvas.tsx`, `designer/Ribbon.tsx`, `designer/formatChart.ts`, `designer/visuals/registry.tsx`, `designer/store.ts`, `viewer/ReportViewer.tsx`, `embed/sdk.ts`, `embed/EmbedHost.tsx`
- Server: new `magbi/themes/*.json`, `magbi/api/themes.py`, a theme table plus migration, organisation and workspace settings
- Scripts: `scripts/magbi_lib.py`, `scripts/qa_gate.py`

**Risks**:
- Saved reports hold literal hex in frames and labels. A one-off migration maps the known ERP Native hexes to token names; anything else stays a hex override.
- Status colours carry meaning. A theme may restyle them but can't remove a status, and the glyph and word always come with the colour.
- Kit tests assert exact hexes. They will check against the resolved theme instead.
- Visual drift on live MSD dashboards. Phase 1 must reproduce today's look exactly: a pixel diff of the 3 Warehouse dashboards before and after.

**Assumptions**:
- MSD stays on a light, locked organisation theme (its standing decision). No built-in theme is dark.
- Accessibility is enforced twice: the validator checks every theme, and High Contrast is there for readers who need more.
- The landing page (`site/site.css`) is marketing and stays outside report theming.

**Jira Tasks**:
| Key | Summary |
|-----|---------|
| TASK-1 | Token model and one source of truth, with no visible change |
| TASK-2 | Nine built-in themes, the gallery and the designer picker |
| TASK-3 | Organisation and workspace themes stored on the server |
| TASK-4 | Mobile and High Contrast in the viewer, and embed theming |
| TASK-5 | Theme validator and a theme-aware QA gate |

---

## 2. Implementation Plan
| Subtask Key | Summary | Acceptance Criteria | Est. | Status |
|-------------|---------|---------------------|------|--------|
| SUB-1.1 | Define the `magbi.theme/1` schema, resolver and merge order | Unit tests for the merge order and for locking | 1d | [x] |
| SUB-1.2 | Move Enterprise Light to `server/magbi/themes/enterprise-light.json` and serve `GET /themes` | `magbi_lib`, web and gate all read it; the 4 copies are deleted | 1d | [x] |
| SUB-1.3 | Theme context, CSS variables and the ECharts theme; the kit reads tokens | `kit.css` has no literal hex; `buildEChartsTheme` is implemented | 2d | [x] |
| SUB-1.4 | Frames and labels store token names, plus a migration for saved reports | The 3 Warehouse dashboards show a 0 px diff before and after | 1d | [x] |
| SUB-2.1 | Write the Classic, Health, Finance, Government and Retail themes | Each passes the validator; statuses unchanged in meaning | 2d | [x] |
| SUB-2.1b | Write the Mobile, Presentation and High Contrast themes (type scale, spacing, touch sizes, gridlines, patterns) | Mobile touch targets at least 44 px; Presentation body text at least 16 px; High Contrast text 7:1 and series told apart by pattern too | 1.5d | [x] |
| SUB-2.2 | Ribbon theme gallery with live previews, and "Customize current theme" | Picking a theme restyles every visual, kit included | 2d | [x] |
| SUB-2.3 | Full Power BI theme JSON import and export | A Power BI theme file round-trips its colours, status, text classes and backgrounds | 1d | [x] |
| SUB-2.4 | Move MSD Enterprise out of the built-ins | It's absent from the product list and available as MSD's organisation theme | 0.5d | [x] |
| SUB-3.1 | Theme table and CRUD API scoped to organisation and workspace, with versions | Permission tests: admins edit organisation themes, editors edit workspace themes | 2d | [x] |
| SUB-3.2 | Default theme per organisation and workspace, with lock | New reports inherit it; a locked brand can't be overridden | 1d | [x] |
| SUB-4.1 | Viewer uses Mobile on phone-width screens, with a manual toggle | Works on every visual type; a locked organisation theme wins | 1d | [x] |
| SUB-4.1b | Viewer High Contrast switch, saved per user, overriding a locked brand | Works on every visual type, kit included | 1d | [x] |
| SUB-4.2 | Embed SDK `theme` option (id, overrides, mode) | The host app can pass a theme id or overrides; locked tokens are ignored | 1d | [x] |
| SUB-5.1 | Theme validator for contrast, colour-blind separation, distinct statuses and completeness | Runs on save and in CI | 1d | [x] |
| SUB-5.2 | QA gate checks against the resolved theme and renders each built-in theme | All 3 Warehouse dashboards pass under all 9 built-in themes | 1d | [x] |

---

## 3. Execution Log
- [x] Analysis and Plan approved 31 Oct 2026 (theme list changed to the 9 above).
- [x] SUB-1.1 to SUB-1.4, Phase 1 (31 Oct 2026). Commits are listed under "Phase 1 result" below.

### Phase 1 result (31 Oct 2026)

| Part | Where |
|------|-------|
| Enterprise Light as the one theme file | `server/magbi/themes/enterprise-light.json` |
| Python loader, completeness check, token names, frame migration | `server/magbi/themes/__init__.py` |
| `GET /api/v1/themes` and `/themes/{id}` | `server/magbi/api/themes.py` |
| Schema, layered resolver with lock, CSS variables, ECharts options, token colours | `web/src/shared/theme.ts` (the web bundles the same JSON through the `@themes` alias) |
| Kit visuals read the report's resolved theme; `kit.css` has no literal colour | `web/src/kit/KitVisual.tsx`, `kit/kit.css`, `kit/tone.ts` |
| Duplicate copies removed | `kit/tone.ts` TOKENS, `designer/standard.ts` ERP_NATIVE and STATUS, `magbi_lib.py` constants, the QA gate's hex list |
| Frames store token names (`fill: "frame"`, `border: "line"`) | `magbi_lib.Page.frame`; saved reports migrated with `python -m scripts.theme_tokens --workspace <id> --report <id> --apply` |
| QA gate checks against the report's own theme, including the report palette and token names | `server/scripts/qa_gate.py` |

**Checks**
- Backend: 524 passed, 17 skipped. Frontend: 63 passed. ruff, mypy and ESLint are clean, and the production build works.
- QA gate (signed in as a viewer): all 3 Warehouse dashboards pass.
- Pixel diff of 69 screenshots before and after. Colours, frames, type and status are identical. The only differences are rows with equal values swapping order (the database returns ties in no fixed order) and single pixels off by 1/255 from anti-aliasing.
- The diff found that Outbound & Transfers had Power BI's default palette saved on it, probably from the ribbon's "Default theme" button. The kit used to ignore it; now it follows the report theme. The palette was restored to Enterprise Light, and the gate now fails any report palette colour that isn't in its theme.

**Left for later phases**
- The classic (non-kit) visuals still take only `theme.colors`. The gallery in Phase 2 will move them onto the resolved theme.
- `shared/themes.ts` (the old ribbon presets, including MSD Enterprise) stays until the Phase 2 gallery replaces it.
- Font sizes stay in `kit.css`. `type.scale` is in the schema for the Mobile and Presentation themes.
- The web Dockerfile builds with `web/` as its context, so it can't see `server/magbi/themes`. It already can't see `deploy/nginx.conf` either, so the web image build needs the repository root as its context.

---

### Phase 2 result (31 Oct 2026)

| Part | Where |
|------|-------|
| 8 new theme files: Classic, Health, Finance, Government, Retail, Mobile, Presentation, High Contrast. Mobile and Presentation extend Enterprise Light and change only what differs | `server/magbi/themes/*.json` |
| Theme checks: text contrast on every surface (4.5:1, or 7:1 where a theme promises it), neighbouring chart colours told apart with normal vision and three kinds of colour blindness, statuses distinct and never reused as chart colours | `server/magbi/themes/validate.py`, the same rules in `web/src/shared/themeCheck.ts` |
| Gallery: every built-in theme drawn in its own colours; picking one restyles the whole report, kit and classic visuals alike | `web/src/designer/ThemeGallery.tsx`, ribbon Format > Themes |
| Customize: page, panels, text, font, text size, chart colours, statuses, corners, gridlines, patterns, with a live preview and every failed check listed; Save stays off until it passes | `web/src/designer/ThemeDialog.tsx`, ribbon Format > Customize |
| Import a Power BI or MagBI theme file; export a Power BI theme that also carries the full MagBI theme, so it opens in Power BI and round-trips here | `web/src/shared/themeFile.ts`, ribbon Import theme / Export theme |
| Kit follows `type.scale`, `type.numberWeight`, `shape.border`, `shape.touch`, `chart.gridlines` and `pattern` (ECharts decals) | `kit/kit.css`, `kit/KitVisual.tsx`, `shared/theme.ts` |
| Classic visuals and the page background take the resolved theme once a report has one; older reports without a theme keep their look | `designer/useReportTheme.ts`, `Charts.tsx`, `Canvas.tsx` |
| MSD Enterprise removed from the product; kept as MSD's organisation theme for Phase 3 | `server/scripts/msd/msd-enterprise.theme.json` |
| `?theme=<id>` previews a built-in theme in the viewer without saving; the QA gate's `--theme` uses it | `viewer/ReportViewer.tsx`, `scripts/qa_gate.py` |

**Changes to Enterprise Light found by the checks**
- Muted text #66758A was 4.02 to 4.48:1 on the page, frames and panel headers, under WCAG AA. It is now #5F6D80 (4.52:1 or better, OKLab distance 2.8, barely visible).
- The Watch label #8F5F27 on its pill was 4.37:1. It is now #8B5C26 (4.58:1).
- The four chart blues are a deliberate light-to-dark ramp. They are now marked `data.style: "ramp"`, which the checks hold to a lower floor for normal vision (8 instead of 15), because kit charts always carry labels.

**Checks**
- All 9 themes pass the Python and the TypeScript checks. An export and re-import of every theme gives back the identical theme.
- Backend: 527 passed, 17 skipped. Frontend: 69 passed. ruff, mypy and ESLint are clean, and the production build works.
- Gallery and Customize driven in headless Chrome: 9 tiles, Enterprise Light marked current, Health turns the page #EEF5F5, and a #D0D0D0 muted text lists 4 contrast failures and keeps Save off.
- QA gate under every theme: see the Phase 3–5 result below.

**Not done in Phase 2**
- SUB-5.1 is partly done: the checks run in Customize and in the test suites, but not yet on the server when a theme is saved (that comes with stored themes in Phase 3).
- Mobile changes type and touch size only. It does not reflow the page, as the analysis says.
- Font scaling keeps the layout fixed, so larger type can shorten text with an ellipsis in tight panels. The theme gate below shows where.

### Phases 3–5 result (31 Oct 2026)

| Part | Where |
|------|-------|
| Saved themes: `themes` table (migration 0006), organisation themes (platform admins) and workspace themes (editors), versions and audit log rows, checked on save (`THEME_FAILS_CHECKS` lists every failed rule) | `server/magbi/api/themes.py`, `metadata/models.py` |
| Resolution: a report's own pick, else the workspace default, else the organisation default, else Enterprise Light; a locked organisation theme always wins, chart colours aside | `web/src/shared/theme.ts` (`themeForReport`) |
| Gallery sections (organisation, workspace, built-in) and a lock notice; Customize saves for the report, the workspace or the organisation | `ThemeGallery.tsx`, `ThemeDialog.tsx` |
| Reader switches in the viewer: High Contrast (kept per browser, wins over a lock) and Larger text (on by default under 768 px) | `viewer/ReportViewer.tsx`, `viewer/readerTheme.ts` |
| Embedding: `?themeId=` and `contrast=1` in the embed link, `setTheme` in the SDK; embed tokens may read their workspace's themes | `embed/sdk.ts`, `api/deps.py` |
| MSD's organisation theme: "MSD ERP Native" (extends Enterprise Light, locked), set by `python -m scripts.msd.set_organisation_theme`; not switched on yet | `server/scripts/msd/` |
| Gate: `--themes all` and `--quick`; CI runs the frontend tests, which check every built-in theme | `scripts/qa_gate.py`, `.github/workflows/ci.yml` |

**Changes from the plan**
- MSD's brand is ERP Native (Enterprise Light), not the old "MSD Enterprise" palette, which is superseded. Locking the old palette would have recoloured every MSD dashboard.
- High Contrast is remembered per browser, not per account.
- Mobile is larger text only. The 44 px touch minimum made the Stock & Expiry heat matrix scroll and is meaningless on a page a phone shrinks to a few hundred pixels; it waits for a phone layout (MAGBI-019 phase 8).

**Fixed during testing** (see the MagBI Test Review artifact): High Contrast KPI cards 2 px too tall; the Mobile heat matrix; a donut pinning a fixed colour (pinned colours can now be `data-1`…); the gate hanging on a shared browser port. Also found end to end and fixed: RLS on a dimension table crashed (500), embedded reports skipped the embed token, cards ignored the measure format.

**Checks**: backend 533 passed, frontend 78 passed; every dashboard passes the gate in all 9 themes (`--themes all --quick`, 30 of 30); one warning remains (a subtitle cut short in Presentation).

## 4. Definition of Done (DoD)
- [ ] Code is written and passes all local tests and lints
- [ ] Single-sentence commit rule followed for all commits
- [ ] SSOT README is fully updated
- [ ] PR description generated from this checklist
