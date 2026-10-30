# Feature: MAGBI-012 — Designer UI overhaul to match Power BI-class mockup

Source: side-by-side audit of the running mockup (`magbi-designer-mockup.html`) against
the current React designer (`web/src/designer/`).  
Deliverable: bring the designer's layout, navigation, theming, and pane architecture
to parity with the mockup so that every panel the mockup shows is present and
interactive in the real app.

---

## Analysis

### What exists and works today

| Feature | Files | Notes |
|---|---|---|
| Canvas with free-form drag | `Canvas.tsx`, `layout.ts` | 1760×990, pointer drag, CSS scale |
| 8-handle resize | `Canvas.tsx:128-180`, `layout.ts:47-83` | All 8 handles, min 80×60 |
| Snap guides | `guides.ts` | 4px reach, edge/center align |
| Visual selection | `store.ts:31`, `Canvas.tsx:58` | Click to select/deselect |
| 6 visual renders | `Charts.tsx`, `render.ts` | Column, bar, line, pie, card, table |
| Undo/redo | `history.ts`, `store.ts:79-86` | JSON-patch, Ctrl+Z/Y |
| Field drag-drop to wells | `DataPane.tsx`, `WellsPanel.tsx` | dnd-kit, auto-routing |
| Filter pane | `FilterPane.tsx`, `filters.ts` | Page-level eq/in filters |
| Cross-filtering | `filters.ts:12-29`, `Canvas.tsx:186-204` | Click category to filter |
| Semantic queries | `query.ts`, `Charts.tsx:37-58` | Build from wells+filters, POST to API |
| Dataset model | `model.ts` | API tables/columns/measures |
| Publish/save | `DesignerPage.tsx:141-165` | POST/PUT report to API |
| Auto-scale | `DesignerPage.tsx:102-113` | ResizeObserver fits page |
| Delete visual | `store.ts:57-66` | Delete/Backspace key |
| Month ordering | `render.ts:112-128` | Auto-sorts months |

### What exists but is incomplete

| Feature | Current | Mockup target | Gap |
|---|---|---|---|
| Visual catalog | 13 types in `catalog.ts`; only 6 render | 25 types in 5-col icon grid; 9 rendered | Missing gauge, waterfall, scatter, funnel, treemap, donut renders; 12 more gallery types |
| Right panel | "Build" pane: gallery + fields + wells in one tab; format tab has title + color | 3 tabs (Data/Format/Analytics): Data = fields + wells; Format = 9 collapsible groups (~30 controls); Analytics = 8 items | Format has 2 fields vs 30+; Analytics absent; Data mixes gallery + fields |
| Ribbon/header | Flat dark bar: name, Undo, Redo, Publish | 6-tab ribbon (Home/Insert/Modeling/View/Format/Help), each with grouped icon buttons | Not a tabbed ribbon |
| Page tabs | Static "Page 1" label | 4 switchable pages + add-page button | No add/switch, store hardcodes `pages[0]` |
| Filter pane | Flat field picker + operator + value | 3-level hierarchy (Visual/Page/Report) with cards + drop zone | No level separation, no visual-level or report-level filters |
| Gallery layout | 2-col text grid | 5-col icon grid, 25 types | No icons, fewer types |
| Format editing | `title` + `color` in `filters.ts:72-74` | 9 groups: General/Title/X-axis/Y-axis/Data colors/Data labels/Legend/Background/Border | 2 fields vs ~30; no toggles, no collapsible groups |

### What is completely missing

| Feature | Description |
|---|---|
| Title bar | Navy bar with logo, file name, save/undo/redo icons |
| Tabbed ribbon | 6 tabs with per-tab grouped icon buttons |
| Status bar | Connection dot, refresh time, visual count, canvas size, page number |
| Context menu | Right-click: Copy/Paste/Bring to front/Send to back/Remove etc. |
| Selection pane | Floating panel listing all visuals |
| Zoom controls | +/− buttons, percentage, fit-to-page |
| Analytics pane | 8 reference-line types |
| Multi-page support | `activePageIndex` + add/switch/rename/delete pages |
| Tooltip preview | Hover card showing field breakdown |
| Grid overlay | Faint grid lines on canvas |
| Visual z-ordering | Bring to front / send to back |
| Copy/paste visuals | Visual clipboard |
| Drillthrough | Page-level drillthrough with filter passthrough |
| Visual icons | All SVG icons for gallery and ribbon |
| MSD theme tokens | CSS variables for navy/blue/orange palette |
| `PropertyPane.tsx` | Empty stub — `return <aside className="property-pane" />` |
| `InteractionEditor.tsx` | Empty stub — `return <div className="interaction-editor" />` |
| `VisualWrapper.tsx` | Empty stub — `return <div className="visual-wrapper" />` |
| All 13 `visuals/*.tsx` | Every one is a 4-line empty div stub |

### Architecture gaps

1. **Single-page hardcode**: `store.ts` references `report.pages[0]` in 7 actions.
   Need `activePageIndex` state and page-switching actions.

2. **No visual registry integration**: `visuals/registry.ts` defines `registerVisual`/
   `getVisual` but `Charts.tsx` ignores it, rendering via its own switch.
   The 13 visual component stubs are never imported.

3. **Monolithic DesignerPage**: All UI in one 281-line component. Needs decomposition
   into TitleBar, Ribbon, LeftPanel, Canvas, RightPanel, PageTabs, StatusBar.

4. **Single side-pane model**: Current "rails" toggle system puts everything in one
   side pane. Mockup has a permanent left panel and a permanent right panel.

5. **No CSS design system**: `designer.css` uses hardcoded colours. Mockup uses
   `--navy`, `--blue`, `--border` etc. — needs full CSS variable system.

6. **Flat format model**: `patchFormat` stores only `title` and `color`.
   The 9-group format pane needs a structured per-visual-type format schema.

---

## Implementation Plan

### Phase 1 — Layout & Theme (unblocks everything)

**MAGBI-012-01: CSS design system**
- Add CSS variables for MSD palette to `designer.css`
- `--navy`, `--blue`, `--blue-light`, `--accent`, `--bg`, `--panel`, `--border`,
  `--text`, `--text2`, `--text3`, `--success`, `--warn`, `--danger`
- Replace all hardcoded colours
- Files: `designer.css`

**MAGBI-012-02: Component decomposition**
- Extract from `DesignerPage.tsx`:
  - `TitleBar.tsx` — logo, file name, save/undo/redo
  - `Ribbon.tsx` — 6 tabs, grouped buttons with inline SVG icons
  - `LeftPanel.tsx` — wraps viz gallery + filter pane
  - `RightPanel.tsx` — Data/Format/Analytics tabs
  - `PageTabs.tsx` — page tab strip + add button
  - `StatusBar.tsx` — connection, refresh, counts
- Wire into `DesignerPage.tsx` as flex column layout
- Files: 7 new components, rewrite `DesignerPage.tsx`

**MAGBI-012-03: Multi-page store**
- Add `activePageIndex` to store state
- Add `addPage`, `switchPage`, `removePage`, `renamePage` actions
- Replace all `pages[0]` references with `pages[activePageIndex]`
- Wire `PageTabs.tsx` to store
- Files: `store.ts`, `PageTabs.tsx`, `Canvas.tsx`

### Phase 2 — Panels

**MAGBI-012-04: Viz gallery rewrite**
- 5-column icon grid with inline SVG for each of 25 types
- Click to insert, active state for selected type
- Files: new `VizGallery.tsx`, update `catalog.ts` with all 25 types

**MAGBI-012-05: Filter pane levels**
- Three-level hierarchy: Visual / Page / Report
- Styled filter cards with field name + value summary
- Drop zone at bottom
- Files: rewrite `FilterPane.tsx`

**MAGBI-012-06: Data pane**
- Field list with expandable tables (chevron toggle)
- Search input
- Well drop zones (Axis/Values/Legend/Tooltips/Drillthrough)
- Separate from viz gallery (gallery moves to left panel)
- Files: rewrite `DataPane.tsx`, `WellsPanel.tsx`

**MAGBI-012-07: Format pane**
- 9 collapsible groups: General, Title, X-axis, Y-axis, Data colors,
  Data labels, Legend, Background, Border
- Control types: toggle switch, text input, number input, colour picker, select
- Structured format schema per visual type
- Files: new `FormatPane.tsx`, new `format-schema.ts`, update `store.ts`

**MAGBI-012-08: Analytics pane**
- 8 analytics items: Trend, Constant, Average, Min, Max,
  Percentile, Error bars, Forecast
- Each item: title with coloured icon, description, click to configure
- Files: new `AnalyticsPane.tsx`

### Phase 3 — Ribbon & Controls

**MAGBI-012-09: Tabbed ribbon**
- 6 tabs (Home/Insert/Modeling/View/Format/Help)
- Each tab has grouped icon buttons matching mockup
- Tab switching shows/hides content panels
- Files: `Ribbon.tsx` (from Phase 1)

**MAGBI-012-10: Zoom controls**
- +/− buttons, zoom percentage display, fit-to-page
- Manual zoom 50–200% overrides auto-scale
- Files: update `Canvas.tsx`, `StatusBar.tsx`

**MAGBI-012-11: Context menu**
- Right-click on canvas/visual shows menu
- Items: Copy, Paste, Bring to front, Send to back, Fit to page,
  Spotlight, Drillthrough, Show as table, Remove
- Files: new `ContextMenu.tsx`, update `Canvas.tsx`

**MAGBI-012-12: Selection pane**
- Floating panel listing all visuals on active page
- Click to select, eye icon to hide/show
- Files: new `SelectionPane.tsx`

### Phase 4 — Visual Rendering

**MAGBI-012-13: Wire visual registry**
- Replace `Charts.tsx` switch with `visuals/registry.ts` dispatch
- Each `visuals/*.tsx` registers itself and renders via ECharts or custom
- Files: `Charts.tsx`, `visuals/registry.ts`, all `visuals/*.tsx`

**MAGBI-012-14: Implement missing visual renders**
- Gauge, waterfall, scatter, funnel, treemap, donut renders via ECharts
- Matrix via TanStack
- KPI, decomp tree, smart narrative via custom React
- Files: `visuals/*.tsx`

### Phase 5 — Interactions

**MAGBI-012-15: Tooltip preview**
- Hover card on visuals showing field breakdown
- Files: new `TooltipPreview.tsx`, update `Canvas.tsx`

**MAGBI-012-16: Visual z-ordering**
- Bring to front / send to back actions in store
- Track `zIndex` per visual
- Files: update `store.ts`, `Canvas.tsx`

**MAGBI-012-17: Copy/paste visuals**
- Clipboard buffer in store, Ctrl+C/V handlers
- Files: update `store.ts`, `DesignerPage.tsx`

**MAGBI-012-18: Drillthrough support**
- Drillthrough page type in report schema
- Filter passthrough on drill action
- Files: update `types/report.ts`, `store.ts`, `Canvas.tsx`

---

## Execution Log

| Subtask | Status | Commit |
|---|---|---|
| MAGBI-012-01 | Done | Phase 1 commit |
| MAGBI-012-02 | Done | Phase 1 commit |
| MAGBI-012-03 | Done | Phase 1 commit |
| MAGBI-012-04 | Done | Phase 2 commit |
| MAGBI-012-05 | Done | Phase 2 commit |
| MAGBI-012-06 | Done | Phase 2 commit |
| MAGBI-012-07 | Done | Phase 2 commit |
| MAGBI-012-08 | Done | Phase 2 commit |
| MAGBI-012-09 | Done | Phase 3 commit |
| MAGBI-012-10 | Done | Phase 3 commit |
| MAGBI-012-11 | Done | Phase 3 commit |
| MAGBI-012-12 | Done | Phase 3 commit |
| MAGBI-012-13 | Done | Phase 4 commit |
| MAGBI-012-14 | Done | Phase 4 commit |
| MAGBI-012-15 | Done | Phase 5 commit |
| MAGBI-012-16 | Done | Phase 5 commit |
| MAGBI-012-17 | Done | Phase 5 commit |
| MAGBI-012-18 | Done | Phase 5 commit |
