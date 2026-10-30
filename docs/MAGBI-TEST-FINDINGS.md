# MagBI Test Findings

**Date**: 2026-10-30
**Branch**: `implementation`

---

## Test 1: General Ledger Dashboard (Excel Import)

**Test Data**: General-Ledger.xlsx (2,000 rows, 10 columns)
**Data Scope**: GL entries Jan 2023 – Jun 2025, 5 accounts, 6 departments, 5 cost centers, 5 currencies
**Totals**: Debit 1,210,240.47 | Credit 1,973,281.93 | Net -763,041.46
**Dataset**: `4dd5dca3-80de-43f1-9ac8-e17ad0beb303` (General Ledger)

### How Data Was Loaded

No Excel/CSV import UI exists in MagBI. Data was loaded by:
1. Reading the .xlsx with openpyxl
2. Connecting directly to the dataset's DuckDB file (`server/data/datasets/<id>/live.duckdb`)
3. Creating a `Ledger` table with all 10 columns + computed `Month` (YYYY-MM) and `Net` (Debit - Credit)
4. Updating the dataset model definition via the API to match the columns

### Issues Found

| # | Severity | Component | Description | Status |
|---|----------|-----------|-------------|--------|
| 1 | critical | Card visual | Numbers display raw floating point: `1210240.4699999997` instead of `1,210,240.47`. No thousand separators, no rounding, no currency symbol | OPEN |
| 2 | critical | Chart tooltip | Tooltip values show floating point artifacts: `40,365.7469999999` | OPEN |
| 3 | critical | State persistence | All designer state is in-memory (Zustand). Refreshing the browser loses ALL work — visuals, pages, field assignments, everything. No auto-save, no save prompt | OPEN |
| 4 | critical | Page freeze | Page became completely unresponsive (required tab close) when rapidly adding fields to a table visual. Likely caused by multiple concurrent query requests without debouncing | OPEN |
| 5 | critical | Delete visuals | Ctrl+A + Delete does not delete visuals reliably. Repeated attempts left visuals on the canvas | OPEN |
| 6 | major | Context menu | Right-click does NOT open the context menu. The context menu appears on Ctrl+V (paste) instead | OPEN |
| 7 | major | Card visual | Card labels are tiny and barely visible. No number formatting options (K/M suffix, decimal places, prefix/suffix) | OPEN |
| 8 | major | Y-axis labels | Y-axis shows raw numbers like "40000" without thousand separators or K/M abbreviations | OPEN |
| 9 | major | X-axis labels | With 30 months of data, X-axis labels (YYYY-MM) overlap and are unreadable. No auto-rotation, no label-skipping | OPEN |
| 10 | major | Drag-and-drop | Dragging fields from the field list to wells is unreliable. The drop target is hard to hit | OPEN |
| 11 | major | Visual placement | New visuals always placed at fixed position (top-left), overlapping existing visuals | OPEN |
| 12 | major | Multi-page persistence | Added pages are lost on reload. Pages exist only in the Zustand store | OPEN |
| 13 | major | Excel/CSV import | No UI to import Excel or CSV files. Had to load via Python script into DuckDB directly | OPEN |
| 14 | minor | Card size | Default card size is small; number barely fits. Power BI auto-sizes font | OPEN |
| 15 | minor | Visual thumbnails | Visual type picker icons are small and hard to distinguish | OPEN |
| 16 | minor | Status bar | No page/report name or save status indicator in status bar | OPEN |

### What Works Well

- **Query engine**: POST /query returns correct aggregated data (SUM, GROUP BY) across 2,000 rows in <100ms
- **13 visual types**: Column, bar, line, pie, card, table, map, slicer, scatter, funnel, gauge, treemap, waterfall
- **Column chart rendering**: ECharts renders clean charts with proper bars, colors, and tooltips
- **Pie chart rendering**: Correct proportional slices with labels
- **Undo/Redo**: Ctrl+Z and Ctrl+Y work correctly
- **Multi-page**: Add page creates blank pages with tab navigation
- **Format pane**: General (size/position), Title (show/text/font/color), Axes (show/units), Data colors (per-series), Data labels (show/position), Legend (show/position), Background
- **Context menu content**: Copy, Paste, Bring to front, Send to back, Drillthrough, Show as table, Remove
- **Field list**: Searchable table columns organized by table
- **Filter pane**: Page/visual/report filters with 9 operators
- **Ribbon**: Full ribbon bar (Home, Insert, Modeling, View, Format, Help)
- **Backend API**: All endpoints work correctly
- **DuckDB performance**: Sub-100ms query times

### Power BI Comparison Gaps

| Feature | MagBI Status | Power BI |
|---------|-------------|----------|
| Number formatting (K/M, decimals, currency) | MISSING | Built-in per-visual |
| Auto-save | MISSING | Continuous to .pbix |
| Excel/CSV import UI | MISSING | 100+ data sources |
| Conditional formatting | MISSING | Data bars, color scales |
| Drill-down / drill-up | MISSING | Hierarchy-based |
| Bookmarks | MISSING | Save/restore states |
| DAX editor UI | MISSING (backend supports DAX) | Formula bar |
| Relationships diagram | MISSING (backend supports) | Model view |
| Mobile layout | MISSING | Phone/tablet editor |
| Custom visuals | MISSING | AppSource marketplace |

---

## Power BI Feature Parity Checklist

| Feature | Status | Notes |
|---------|--------|-------|
| Create workspace | DONE | Works via API and UI |
| Connect to SQL Server | DONE | Full form with test |
| Browse and select tables | DONE | Schema/table browser |
| Import data (refresh) | DONE | POST /refresh works |
| Scheduled refresh | DONE | Cron scheduling |
| Add visual to canvas | DONE | Click type → appears |
| Drag field to well | PARTIAL | Unreliable drop targets |
| Move and resize visuals | DONE | Drag handles work |
| Column chart | DONE | Renders correctly |
| Bar chart | DONE | Available |
| Line chart | DONE | Renders with data |
| Pie/Donut chart | DONE | Correct slices |
| Card (single value) | PARTIAL | No number formatting |
| Table | PARTIAL | Froze on field add |
| Scatter plot | PARTIAL | Available, untested |
| Funnel | PARTIAL | Available, untested |
| Gauge | PARTIAL | No target support |
| Treemap | PARTIAL | Available, untested |
| Waterfall | PARTIAL | Available, untested |
| Slicer | PARTIAL | Exists, untested e2e |
| Page filters | DONE | 9 operators |
| Visual-level filters | DONE | Filter tab |
| Report-level filters | DONE | Filter tab |
| Cross-filtering | PARTIAL | InteractionEditor exists |
| Format: chart title | DONE | Show/text/font/color |
| Format: axis labels | DONE | Show/display units |
| Format: data labels | DONE | Show/position |
| Format: legend | DONE | Show/position |
| Format: colors | DONE | Per-series pickers |
| Analytics: average line | DONE | Analytics pane |
| Analytics: trend line | DONE | Analytics pane |
| Multi-page report | PARTIAL | Works but not saved |
| Copy/paste visuals | PARTIAL | Triggers context menu |
| Undo/redo | DONE | Ctrl+Z/Y work |
| Keyboard shortcuts | PARTIAL | Delete unreliable |
| Context menu | PARTIAL | Wrong trigger (Ctrl+V not right-click) |
| Export to PNG | DONE | ECharts getDataURL |
| Export to PDF | DONE | Print view |
| Publish report | DONE | 201 Created |
| Embed token | PARTIAL | Backend API exists |
| Theme/branding | DONE | MSD Enterprise + Default |
| Loading states | PARTIAL | Some pages |
| Error handling | PARTIAL | Retry buttons exist |

---

## Priority Fix Order

### P0 — Must Fix (Blocks usability)
1. **Number formatting** — Round to 2 decimals, add thousand separators, support K/M suffix on cards, tooltips, and axes
2. **State persistence** — Auto-save report to backend or warn before losing work on page refresh
3. **Query debouncing** — Debounce rapid field additions to prevent concurrent query flood and page freeze
4. **Delete visuals** — Fix Ctrl+A + Delete to reliably remove selected visuals

### P1 — Should Fix (Poor UX)
5. **Right-click context menu** — Wire to `contextmenu` event, not Ctrl+V
6. **Smart visual placement** — New visuals should find empty canvas space
7. **X-axis label overflow** — Auto-rotate or skip labels when they overlap
8. **Drag-and-drop reliability** — Improve drop zone hit targets for field wells

### P2 — Nice to Have
9. **Excel/CSV import UI** — Add "Get Data > File" option
10. **Card auto-sizing** — Scale font to fill card area
11. **Save indicator** — Show saved/unsaved status in status bar
12. **DAX editor UI** — Create measures from the UI

---

## Test 2: Sales Dashboard (from prior session)

Dataset `efbf92b3-abc0-4cb0-81ba-a06fa8e2fc24` — Sales table (18 rows, Jan–Jun × East/West/North).
Three published reports were created: Sales Executive Summary, Regional Analysis, Formatted Report.
The designer opened the oldest report for a dataset; a `?report=` link now opens the named one.
Total Revenue 261,100 and Total Units 3,160 confirmed.
Gauge still has no target. Waterfall plots the values it is given.
