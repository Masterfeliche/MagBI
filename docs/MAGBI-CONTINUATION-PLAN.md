# MagBI v2 — Continuation Plan for AI Agent

**Date**: 2026-10-30
**Branch**: `implementation`
**Repo**: https://github.com/Masterfeliche/MagBI.git
**Status**: Phase 1 COMPLETE. Phases 2, 3, 4 remain.

---

## What Is MagBI

MagBI is a **full replacement for Microsoft Power BI** — not just for 8 ERP modules but for everything the organization uses Power BI for. The goal is to eliminate Fabric embedding costs entirely.

**Stack**: Python (FastAPI) + DuckDB + sqlglot backend, React + TypeScript + ECharts frontend, Zustand state management, dnd-kit drag-drop.

---

## What Is Done (Phase 1)

### Backend (was already built before this session)
All APIs are implemented and working. **Do not modify backend code unless fixing a bug.**

- SQL Server connector (pyodbc + ODBC Driver 18) — `server/magbi/connectors/sqlserver.py`
- DAX compiler (SUM, CALCULATE, TOTALYTD, SAMEPERIODLASTYEAR, DATEADD, VAR) — `server/magbi/dax/`
- Query engine: semantic query → bind → SQL gen (sqlglot) → DuckDB → DSR — `server/magbi/engine/`
- Data refresh pipeline: queue → import (Arrow batches) → staging DuckDB → atomic swap to live — `server/magbi/refresh/`
- RLS with DAX expression compilation — `server/magbi/engine/rls.py`
- Credential encryption (AES-256-GCM) — `server/magbi/auth/credentials.py`
- Cron-based refresh scheduling — `server/magbi/refresh/scheduler.py`
- All REST endpoints — `server/magbi/api/`

### Frontend — Phase 1 Management UI (just built)
- `web/src/workspace/AppShell.tsx` — Navy topbar, MagBI logo, breadcrumbs
- `web/src/workspace/WorkspaceList.tsx` — Card grid with inline create form
- `web/src/workspace/WorkspaceDetail.tsx` — Tabbed page: Datasets | Reports | Connections
- `web/src/workspace/DatasetList.tsx` — Table with name, mode, updated date
- `web/src/workspace/ReportList.tsx` — Table with name, dataset ID, updated date
- `web/src/workspace/ConnectionList.tsx` — Table with inline Test button
- `web/src/workspace/ConnectionForm.tsx` — Full SQL Server form (host, port, DB, auth, encrypt, test, save)
- `web/src/workspace/DatasetWizard.tsx` — 3-step wizard: Connection → Tables → Name & Create
- `web/src/workspace/workspace.css` — Complete styling for all management pages
- `web/src/routes.tsx` — Layout routes with AppShell wrapper

### Frontend — Designer (was already built, enhanced in this session)
- 13 visual types: column, bar, line, pie, card, table, map, slicer, scatter, funnel, gauge, treemap, waterfall
- Full editing: move, resize, copy/paste, undo/redo, keyboard shortcuts, context menu
- dnd-kit field binding, multi-page, page filters, cross-filtering
- ECharts rendering pipeline: wells → buildQuery() → POST /query → DSR → buildModel() → ECharts option

---

## What To Build — Phases 2, 3, 4

### Phase 2: Data Refresh + "Get Data" Flow

#### 2.1 RefreshPanel (`web/src/workspace/RefreshPanel.tsx`)
- "Refresh now" button → `POST /workspaces/{wid}/datasets/{did}/refresh`
- Poll status every 3s → queued/running/succeeded/failed badge with duration
- History table showing past runs, errors, row counts
- Usable from both DatasetList AND from the designer's StatusBar

#### 2.2 ScheduleEditor (`web/src/workspace/ScheduleEditor.tsx`)
- Embed inside RefreshPanel
- Presets: hourly, every 6h, daily, weekly
- Raw cron input for advanced users
- `PUT /workspaces/{wid}/datasets/{did}/schedule` to set
- `DELETE /workspaces/{wid}/datasets/{did}/schedule` to remove

#### 2.3 Wire Ribbon Buttons (`web/src/designer/Ribbon.tsx`)
The Ribbon already renders buttons but most have no handlers:
- **"Refresh"** button: trigger `POST /datasets/{did}/refresh`, show progress in StatusBar
- **"Get data"** button: open modal with `TableBrowser` component (extract from DatasetWizard), merge new tables into definition, trigger refresh
- **"Publish"** button: already works (201 Created confirmed in E2E test)

**Important**: The `TableBrowser` should be extracted as a reusable component from DatasetWizard into `web/src/workspace/TableBrowser.tsx`, then imported by both the wizard and the "Get data" modal.

#### Backend APIs (all exist, just call them):
```
POST   /workspaces/{wid}/datasets/{did}/refresh          → trigger import
GET    /workspaces/{wid}/datasets/{did}/refresh           → current status + history
PUT    /workspaces/{wid}/datasets/{did}/schedule          → {cron: "0 6 * * *"}
DELETE /workspaces/{wid}/datasets/{did}/schedule           → remove schedule
GET    /workspaces/{wid}/connections/{cid}/schemas         → {schemas: [...]}
GET    /workspaces/{wid}/connections/{cid}/tables?schema=  → {tables: [{schema, name, kind, estimated_rows, columns}]}
```

---

### Phase 3: Designer Rendering Improvements

#### 3.1 FormatPane → ECharts Wiring (`web/src/designer/visuals/registry.tsx`)
FormatPane already stores properties via `setProperties()`. The renderers just don't read them. Map these:

| FormatPane Property | ECharts Option |
|---|---|
| `titleShow` / `titleText` / `titleFontSize` / `titleColor` / `titleAlign` | `title.*` |
| `xShow` / `xFontSize` / `xColor` | `xAxis.axisLabel.*` |
| `yShow` / `yUnits` | `yAxis.show`, formatter (K/M) |
| `labelsShow` / `labelsPos` | `series[].label.*` |
| `legendShow` / `legendPos` | `legend.*` |
| `color` / `color2` | `color[]` |

Background/border → CSS on wrapper div in `Canvas.tsx`.

#### 3.2 Analytics Lines (`web/src/designer/visuals/registry.tsx`)
Read `analytics_average` / `analytics_min` / `analytics_max` / `analytics_constant` → ECharts `markLine.data` entries.
`analytics_trend` → linear regression in JS → dashed line series.
AnalyticsPane (`web/src/designer/AnalyticsPane.tsx`) already stores these toggles — no pane changes needed.

#### 3.3 Slicer with Data Values (`web/src/designer/Charts.tsx` — SlicerField)
Replace the text input slicer with:
- Query distinct values via `POST /query` for the slicer's bound column
- Render as searchable checkbox list (Power BI style)
- Toggle adds/removes page-level filters

#### 3.4 Theme System
- Create `web/src/shared/themes/` with preset themes
- **MSD Enterprise** theme (navy/blue/orange — `--navy: #1B2A4A; --blue: #2B5797; --accent: #E8913A`)
- Replace hardcoded `PALETTE` in `registry.tsx` with `report.theme.colors`
- Wire Ribbon "Theme" button to theme picker modal

---

### Phase 4: Enterprise Polish

#### 4.1 Loading/Error/Empty States
All pages: spinners, error messages with retry, empty-state guidance (some are already done from Phase 1, but verify all paths).

#### 4.2 Export
Wire Ribbon "Export" button:
- **PNG**: ECharts `getDataURL()` on each visual
- **PDF**: Use jspdf or similar library

#### 4.3 Filter Pane Enhancements
- Visual-level filters (currently only page-level)
- Report-level filters
- More operators: neq, gt, gte, lt, lte, contains, startsWith (backend supports all 12)
- Value autocomplete from data

#### 4.4 InteractionEditor (`web/src/designer/InteractionEditor.tsx`)
Currently an empty stub. Build:
- Per-visual cross-filter/highlight/none targeting
- Uses `visual.interactions` property (type already defined in `web/src/types/report.ts`)

#### 4.5 Embed Token Support
Backend already has `POST /embed-tokens` and embed-only workspace roles. Build:
- Embed configuration page for sharing dashboards externally
- This is the Power BI Embedded replacement

---

## Key Architecture Details

### API Wrapper
All API calls go through `web/src/shared/api.ts`:
```typescript
apiFetch<T>(path: string, init?: RequestInit): Promise<T>
```
Prepends `/api/v1`, attaches JWT token from localStorage.

### State Management
- Management pages: `useState` + `useEffect` + `apiFetch`. No shared state store.
- Designer only: Zustand store at `web/src/designer/store.ts` with undo/redo (JSON-patch via fast-json-patch).

### CSS Variables (defined in `web/src/designer/designer.css`)
```css
--navy: #1B2A4A; --blue: #2B5797; --blue-light: #3A7BD5; --blue-hover: #4A8BE5;
--accent: #E8913A; --bg: #F3F4F6; --panel: #FFFFFF; --border: #E0E3E8;
--text: #1E293B; --text2: #64748B; --text3: #94A3B8;
--success: #10B981; --warn: #F59E0B; --danger: #EF4444;
```

### Backend Response Format
All backend responses use **snake_case** (e.g. `dataset_id`, `updated_at`, `connection_id`). The TypeScript types in `web/src/types/api.ts` already match.

### Dev Server Setup
```bash
# Backend (port 8000)
cd server && python dev_server.py

# Frontend (port 3000, proxies /api to :8000)
cd web && npm run dev
```

The dev server at `server/dev_server.py` auto-creates the database, uses SQLite, and sets `insecure_admin_api=True` (no auth needed for dev).

### Test Data
A test workspace and dataset exist from E2E testing:
- Workspace ID: `4461296c-f228-4607-943c-5997846333d5`
- Dataset ID: `efbf92b3-abc0-4cb0-81ba-a06fa8e2fc24`
- DuckDB data: `server/data/datasets/efbf92b3-abc0-4cb0-81ba-a06fa8e2fc24/live.duckdb`
- 18 rows: Sales table (Month, Revenue, Region, Units) for Jan–Jun × East/West/North

### Known Issue Fixed
- Redis cache: `server/magbi/api/query.py:88` — `_cache()` returns `None` for `dev` and `test` environments (no Redis needed in dev)

---

## Verification Checklist

After implementing each phase, verify:

| Phase | Test |
|-------|------|
| 2 | Click Refresh → import completes → charts show data → schedule set → "Get data" adds tables |
| 3 | Format title → chart title changes → enable avg line → line appears → slicer shows values → theme applies |
| 4 | Loading spinners visible → export PNG → visual-level filter works → embed token generated |

### How to verify
1. Start backend: `cd server && python dev_server.py`
2. Start frontend: `cd web && npm run dev`
3. Open http://localhost:3000/workspaces
4. Navigate to workspace → dataset → designer
5. Test the feature you built

---

## Sequencing

```
Phase 2 (data refresh + get data)  ← depends on Phase 1 (reuses TableBrowser)
Phase 3 (designer rendering)      ← independent, can run parallel with Phase 2
Phase 4 (enterprise polish)        ← independent, can run parallel with Phase 3
```

All three remaining phases can theoretically be built in parallel since they touch different files. Phase 2 touches workspace/ files, Phase 3 touches designer/ files, Phase 4 touches both but different components.

---

## Phase 5: Build-Test-Improve Loop (after Phases 2-4)

Once Phases 2, 3, and 4 are implemented, enter a continuous improvement loop. **Do not stop after building features — test them by building real dashboards and fix every issue you find.**

### Step 1: Build 3 Test Dashboards

Create 3 dashboards using the test dataset (18 rows: Sales with Month, Revenue, Region, Units). Each must exercise different MagBI capabilities:

#### Dashboard A — "Sales Executive Summary"
- **Page 1**: Card (Total Revenue), Card (Total Units), Column chart (Revenue by Month), Pie chart (Revenue by Region)
- **Page 2**: Table (all data), Bar chart (Units by Region), Line chart (Revenue trend over months)
- Tests: multi-page, card visuals, basic charts, page tabs

#### Dashboard B — "Regional Analysis"
- **Page 1**: Slicer (filter by Region), Column chart (Revenue by Month filtered), Card (filtered total)
- **Page 2**: Scatter plot (Revenue vs Units by Month), Funnel (Revenue by Region descending)
- Tests: slicer filtering, cross-page state, scatter/funnel visuals, page filters

#### Dashboard C — "Formatted Report"
- **Page 1**: Column chart with custom title, axis labels, legend, data labels, analytics average line, custom colors via FormatPane, treemap (Revenue by Region)
- **Page 2**: Gauge (Revenue vs target), Waterfall (monthly revenue changes)
- Tests: FormatPane properties, analytics lines, theme colors, gauge/waterfall/treemap visuals

### Step 2: Record Findings

After building each dashboard, document every issue in `docs/MAGBI-TEST-FINDINGS.md`:

```markdown
## Dashboard [A/B/C] — [Name]

### Issues Found
| # | Severity | Component | Description | Status |
|---|----------|-----------|-------------|--------|
| 1 | critical | ... | ... | OPEN |
| 2 | major | ... | ... | FIXED |
| 3 | minor | ... | ... | OPEN |

### What Works Well
- [list what worked correctly]

### Power BI Comparison Gaps
- [list features that Power BI has but MagBI is missing or inferior]
```

Severity levels:
- **critical**: Feature broken, crashes, or produces wrong data
- **major**: Feature works but UX is poor, confusing, or significantly worse than Power BI
- **minor**: Cosmetic issues, small polish items

### Step 3: Fix and Improve

After documenting findings from all 3 dashboards:
1. Fix all **critical** issues first
2. Fix all **major** issues
3. Fix **minor** issues
4. Re-test each dashboard after fixes
5. Update `docs/MAGBI-TEST-FINDINGS.md` with status changes (OPEN → FIXED)

### Step 4: Repeat

After fixing, rebuild the dashboards from scratch (delete and recreate) to verify the fixes work in a clean flow. If new issues surface, document and fix them. Continue until:
- All 3 dashboards build without any critical or major issues
- Every visual type renders correctly with data
- FormatPane changes visibly affect charts
- Slicer filters data across visuals
- Export produces clean PNG/PDF
- Page navigation, undo/redo, copy/paste all work
- The experience feels comparable to Power BI Desktop for basic dashboard building

### Power BI Feature Parity Checklist

Compare MagBI against these core Power BI Desktop capabilities. Mark each as DONE, PARTIAL, or MISSING:

| Feature | Status | Notes |
|---------|--------|-------|
| Create workspace | | |
| Connect to SQL Server | | |
| Browse and select tables | | |
| Import data (refresh) | | |
| Scheduled refresh | | |
| Add visual to canvas | | |
| Drag field to well (axis/value/legend) | | |
| Move and resize visuals | | |
| Column chart | | |
| Bar chart | | |
| Line chart | | |
| Pie/Donut chart | | |
| Card (single value) | | |
| Table | | |
| Scatter plot | | |
| Funnel | | |
| Gauge | | |
| Treemap | | |
| Waterfall | | |
| Slicer (interactive filter) | | |
| Page filters | | |
| Visual-level filters | | |
| Report-level filters | | |
| Cross-filtering between visuals | | |
| Format: chart title | | |
| Format: axis labels | | |
| Format: data labels | | |
| Format: legend | | |
| Format: colors/palette | | |
| Analytics: average line | | |
| Analytics: trend line | | |
| Multi-page report | | |
| Copy/paste visuals | | |
| Undo/redo | | |
| Keyboard shortcuts | | |
| Context menu (right-click) | | |
| Export to PNG | | |
| Export to PDF | | |
| Publish report | | |
| Embed token for external sharing | | |
| Theme/branding | | |
| Loading states | | |
| Error handling | | |

Update this table as you test. The goal is all rows showing DONE.

---

## Commit Convention
```
type(scope): description (imperative, max 72 chars, no period)
```
Types: feat, fix, docs, refactor, test. Scopes: designer, workspace, refresh, api.
