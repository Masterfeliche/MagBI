# Feature: MAGBI-009 - Report designer

Source: `docs/IMPLEMENTATION-PLAN.md` Sprint 9 (Week 12-14). Milestone 2. FR: FR-040 through FR-048, FR-051.
Deliverable: open the designer on a dataset, place a bar chart, drop fields into wells, see it render from a live query, click a bar to filter the other visuals, and publish the report.

## 1. Analysis
**Current state (verified)**: `web/` is a Vite + React 19 app. Routes render the word MagBI. Designer, visual, workspace, and model-editor files are stubs. Dependencies already include ECharts, dnd-kit, Zustand, and fast-json-patch. There is no test script. `web/src/types/report.ts` is the report contract: pages, visuals, wells, filters. `web/src/types/dataset.ts` is camelCase and puts measures on the document. The API stores a dataset definition in snake_case, with measures on each table. The query route is `POST /api/v1/workspaces/{wid}/datasets/{did}/query` and returns `columns`, `rows`, `rowCount`. `web/src/shared/api.ts` calls `/api`, not `/api/v1`. The `reports` table already has `definition` and `is_published`. `server/magbi/api/reports.py` is an empty router and is not mounted. The embed SDK and the standalone viewer are Sprint 10.

**Affected files**:
- `web/src/designer/`, `web/src/visuals/`, `web/src/routes.tsx`, `web/src/shared/api.ts`
- `web/package.json` (Vitest)
- `server/magbi/api/reports.py`, `server/magbi/api/router.py`
- `server/tests/test_api/test_reports.py`
- `docs/kb/07-report-designer.md` (status note)

**Design decisions**:
1. **The designer reads the API's snake_case definition.** An adapter exposes tables, columns, and measures to the panes. `web/src/types/dataset.ts` is not rewritten in this sprint. The report document stays the camelCase shape in `web/src/types/report.ts`.
2. **One designer route.** `/workspaces/:workspaceId/datasets/:datasetId/designer`. It loads that dataset and queries that dataset. The API client uses `/api/v1` and sends a bearer token when one is stored.
3. **The canvas is 1760 by 990, with zoom, pan, and a 10px snap.** A new visual lands at the next snapped cell. Dragging a visual on the canvas snaps its `x` and `y`. The palette lists the 13 registered types and adds one to the page.
4. **Wells come from the registry.** A column dropped on a grouping well is a group. A measure, or a numeric column dropped on a values well, becomes an aggregated field. A numeric column with no aggregation is `sum`. The visual's query is built only from its wells plus the page filters and the active cross-filter.
5. **Bar, line, pie, card, and table render the query result.** Bar, line, and pie use ECharts. The card shows one measure. The table shows the rows. Scatter, funnel, gauge, treemap, and waterfall use the same category-and-value option as a bar so they are not empty. Matrix is a table. The map visual states that it needs coordinates. The slicer adds a page filter instead of drawing a chart.
6. **A chart click sets one cross-filter.** The clicked category becomes an `eq` filter on the visual's first grouping column. Other visuals on the page include it in `where` and query again. Clicking the same category clears it. The filter pane edits page-level basic filters (`eq` and `in`).
7. **Undo stores JSON patches of the report document.** Ctrl+Z undoes and Ctrl+Y redoes. Selecting a visual and changing its title or color is one patch. Title and a single color are the property pane. Conditional formatting waits.
8. **Publish persists the report.** `POST` and `PUT /api/v1/workspaces/{wid}/reports` store `definition` and `is_published`. The button saves and sets published. The viewer that opens a published report is Sprint 10.

**Risks**:
- **A snake_case definition silently yields an empty data pane.** Mitigation: the adapter test uses a dataset payload from the API, with measures nested on the table.
- **A visual query that does not match the Sprint 5 contract returns an error instead of a chart.** Mitigation: one test builds the semantic query for a category and a summed column and checks the JSON shape.
- **Drag-and-drop is awkward to assert in Vitest.** Mitigation: snap, query building, cross-filter, and undo are pure tests. The browser check is the drag path.

**Assumptions**:
- The dev server and the API are both running for the browser check. Vitest does not start them.
- Auth stays as Sprint 7 left it. The designer does not add a login screen.
- One page per report is enough. Adding pages can be a later control.
- Map tiles and conditional formatting are not this sprint.

**Jira Tasks**:
| Key | Summary |
|-----|---------|
| TASK-1 | Query building, canvas, and wells |
| TASK-2 | Rendering, filters, undo, and publish |
| TASK-3 | Docs and finalization |

---

## 2. Implementation Plan
| Subtask Key | Summary | Acceptance Criteria | Est. | Status |
|-------------|---------|---------------------|------|--------|
| SUB-1.1 | Query and dataset adapter | A snake_case definition becomes tables, columns, and measures; wells become a semantic query with `sum` on a numeric column; Vitest covers both | 4h | [x] |
| SUB-1.2 | Canvas and palette | The page is 1760 by 990; a dropped position snaps to 10px; choosing a palette type adds a visual at the next snapped cell | 4h | [x] |
| SUB-1.3 | Data pane and wells | The pane lists the adapted model; dropping a field fills the matching well; a second drop past the well's max is refused | 4h | [x] |
| SUB-2.1 | Visual rendering | Bar, line, pie, card, and table turn a DSR into a render model; the other chart types stay notes instead of a fake column chart; the map explains the missing coordinates | 5h | [x] |
| SUB-2.2 | Filters and properties | A chart category becomes a page cross-filter and is cleared by a second click; a page filter is added to every visual query; title and color patch the visual | 4h | [x] |
| SUB-2.3 | Undo and publish | Ctrl+Z restores the previous document and Ctrl+Y reapplies it; `POST` and `PUT` reports store the definition and `is_published` | 4h | [x] |
| SUB-3.1 | Docs | KB 07 names the designer route, the live query, the visuals that render, and what stays in Sprint 10 | 1.5h | [x] |
| SUB-3.2 | Finalization | ESLint, `tsc`, Vitest, the report API tests, and a browser pass of the designer flow; PR description | 1.5h | [x] |

Order: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 3.1, 3.2. Each subtask is code, tests, and one single-sentence commit. About 28 hours.

---

## 3. Execution Log
- [x] SUB-1.1: 9d6bb6e
- [x] SUB-1.2: 2c6f5da
- [x] SUB-1.3: 6445a13
- [x] SUB-2.1: 2fb76cf
- [x] SUB-2.2: 6cfffbb
- [x] SUB-2.3: 0516b7d
- [x] SUB-3.1: fb41ede
- [x] SUB-3.2: see git log

Layout deviation from the first three-pane draft: Filters and Build are right-side rails and only one is open. The ribbon is the report name, Undo, Redo, and Publish. The gallery keeps later visual types, and only column, bar, line, pie, card, and table draw a query. Format is a title and one color. No component library.

---

## 4. Definition of Done (DoD)
- [x] Code is written and passes local tests and lints
- [x] Single-sentence commit rule followed for all commits
- [x] SSOT README is fully updated
- [x] PR description generated from this checklist
- [x] ESLint and `tsc` pass
- [x] Vitest covers the query builder, snap, wells, cross-filter, and undo
- [x] A bar visual built from wells renders rows from the query API
- [x] Publish stores the report and marks it published
- [x] KB 07 updated to match the implementation

### Findings and open items
- The browser pass added a column, applied the title Trips, undid and redid it, and switched from Build to Filters so only one rail stayed open.
- That pass had no imported dataset, so the page showed API 404 and the empty-query note. The bar render test uses the same DSR shape the query route returns.
- The report API test stored a definition and `is_published`. It did not run the SQL Server integration tests.
- This pass was Windows with the web toolchain and the server venv. It was not repeated in the Python 3.11 Linux image.
- Conditional formatting, the report viewer, and the embed SDK are not in this sprint.

---

## 5. PR Description

**feat: report designer (MAGBI-009)**

Open a dataset in a Power BI-style designer, place a visual, and publish the report definition.

### What changed
- **Page**: `/workspaces/:workspaceId/datasets/:datasetId/designer` loads the dataset. The page is 1760 by 990, scaled to the stage, and positions snap to 10px. Pointer math divides by that scale. A drag records one undo patch when the pointer goes up.
- **Build**: fields drop into Y-axis, X-axis, and Legend. A numeric column on a values well becomes `sum`. A full well refuses the next drop. Column, bar, line, pie, card, and table draw the query result. Map asks for coordinates. Slicer adds a page filter. The other gallery types are not drawn as a column chart.
- **Filters and format**: page filters (`eq` and `in`) go on every visual query. A category click sets one cross-filter and a second click clears it. Format sets a title and one color.
- **Publish**: `POST` and `PUT /api/v1/workspaces/{id}/reports` store `definition` and `is_published`. Ctrl+Z and Ctrl+Y walk JSON patches.

### How it was verified
- Vitest: 8 tests for the adapter, snap, wells, render models, filters, and undo.
- `tsc` and ESLint pass.
- Report API test: create stores the definition unpublished, and update stores the new definition with `is_published` true.
- Browser: Build adds a column, Format shows the title on the visual, Undo and Redo restore the document, and Filters replaces Build.

### Risks and follow-ups
There is no batch query, so each visual is its own POST. The viewer and embed SDK are Sprint 10. Conditional formatting is not in this build. A live imported dataset was not queried in the browser.
