# Feature: MAGBI-013 - Remaining MagBI implementation from GL test plan

Source: `C:\Users\admin\Downloads\MagBI Implementation Plan.md` (35 tasks, Phases 1–4) checked against this worktree on `implementation`. MAGBI-010 (viewer and embed SDK) stays the ticket for Tracks 4–5; this file is the sequence of record so those tasks are not started out of order.

Deliverable: a designer that formats and saves correctly, Excel/CSV load without Python, measures in the UI, a read-only viewer, embed with RLS, then remaining Power BI interaction and model gaps. Do not rebuild work that already exists.

---

## 1. Analysis

The Downloads file is a GL punch list plus a Power BI parity backlog. The first 13 tasks match `docs/MAGBI-TEST-FINDINGS.md`. Tasks 14–35 are new product work. Phase numbers in that file **do not** match `docs/MAGBI-CONTINUATION-PLAN.md` (continuation Phase 2 is refresh/Get Data; Downloads Phase 2 is slicer/drill/bookmarks). Agents follow **this README**, not the Downloads Architecture Notes.

GL fixture used for every browser check:

| Item | Value |
|------|-------|
| Workspace | `4461296c-f228-4607-943c-5997846333d5` |
| Dataset | `4dd5dca3-80de-43f1-9ac8-e17ad0beb303` (General Ledger) |
| Table | Ledger (12 columns including Month and Net) |
| Rows | 2,000 |
| Totals | Debit `1,210,240.47` · Credit `1,973,281.93` · Net **`+763,041.46`** (credit − debit). The Downloads file’s −763,041.46 is the wrong sign. |

### Already in the tree — do not rebuild

| Downloads task | Evidence |
|----------------|----------|
| 1 Number format | `formatNumber` in `formatChart.ts`; Vitest; card/tooltip/Y-axis in `registry.tsx` |
| 2 Auto-save | 2s PUT `/workspaces/{wid}/reports/{rid}` from `DesignerPage.tsx` |
| 3 Query debounce | 300ms + `AbortController` in `Charts.tsx` (not `registry.tsx`) |
| 4 Delete all | `removeAllVisuals()` one undo; Ctrl+A then Delete on `window` |
| 5 Context menu | `onContextMenu` on the stage; Ctrl+V pastes only |
| 6 Placement | `addVisual` passes `page.visuals` into `placeVisual` |
| 7 Axis rotation | `categoryAxisLabel`: count > 12 → rotate 45° |
| 11 Save indicator | `saveStatus` + StatusBar dot |
| 14 Slicer (list) | Distinct values, search, checkboxes, page `in` filter |
| 15 Cross-filter (filter mode) | Chart click → `onCategory`; Interact tab stores mode |
| 20–24 Workspace / connections / wizard / refresh | Real pages, not stubs |
| 26 Theme presets | MSD Enterprise + Default palettes |
| 28 Embed page (partial) | Mints token if a service token exists |
| 30 PNG + print PDF | `exportReport.ts` |

### Still open (this ticket’s work)

| Downloads task | Gap |
|----------------|-----|
| 8 Well drop | Highlight exists; no “Drag field here” placeholder |
| 9 Excel/CSV upload | Get Data only adds SQL tables; no file endpoint |
| 10 Card auto-size | Default still `360×140`; font does not scale |
| 12 DAX editor | `MeasureEditor` is an empty div; ribbon Measure is dead |
| 13 Visual icons | Insert tab is text buttons |
| 14 leftover | No dropdown / range / Select All |
| 15 leftover | Cross-highlight does not dim to 30% |
| 16–18 | Conditional format, drill hierarchy, bookmarks |
| 19 leftover | No Tooltips well |
| 21 leftover | No Members tab |
| 25 Model view | `RelationshipDialog` is empty; backend relationships exist |
| 26 leftover | No Power BI theme JSON import |
| 27 Viewer | Reports only open in the designer |
| 28 leftover | No iframe host, no `magbi-embed.js`, no origin CSP |
| 29 RLS UI | Engine exists; no Manage roles / View as |
| 30 leftover | No jsPDF file, no visual-data XLSX |

Out of this ticket: mobile layout (31), subscriptions (32), extra connectors (33), admin console (34), ERP/i18n/AI (35). Sprint 11 ERP migration stays with the other agent.

### Wrong instructions in the Downloads file — ignore

| Plan says | Use instead |
|-----------|-------------|
| `GET/PUT /reports/{id}` | `PUT /workspaces/{wid}/reports/{rid}`. There is no get-one-report route yet (Track 4 adds it) |
| `POST /query` | `POST /workspaces/{wid}/datasets/{did}/query` |
| `POST /datasets/{id}/measures` | `POST .../datasets/{did}/definition/measures` |
| `POST /embed-tokens` | `POST /embed/token` |
| Zustand `produce` (Immer) | JSON-patch `commit` in `store.ts` |
| Query `useEffect` in `registry.tsx` | `Charts.tsx` |
| `applyFormat()` | `formatNumber` / `categoryAxisLabel` / existing format props |
| N× `removeVisual` for select-all | `removeAllVisuals()` (one history entry) |
| GetDataDialog / WorkspaceList / RefreshPanel are stubs | They are implemented; extend, do not replace |

**Affected files** (by track; new files marked):

- Track 0: no code unless a regression fails
- Track 1: `RightPanel.tsx`, `designer.css`, `Charts.tsx`, `layout.ts`, `Ribbon.tsx`
- Track 2: `server/magbi/api/datasets.py` (new upload), `GetDataDialog.tsx`, `Ribbon.tsx`
- Track 3: `web/src/model-editor/MeasureEditor.tsx`, `Ribbon.tsx`, `RightPanel.tsx`, `web/src/shared/api.ts`
- Track 4 (MAGBI-010): `server/magbi/api/reports.py`, new `web/src/viewer/ReportViewer.tsx`, `routes.tsx`, `ReportList.tsx`
- Track 5 (MAGBI-010 + RLS): `web/src/workspace/EmbedPage.tsx`, new `web/embed-sdk/magbi-embed.js` or `web/src/embed/sdk.ts`, `server/magbi/api/embed.py`, new `RlsRolesDialog.tsx` / `ViewAsDialog.tsx`
- Track 6: `Charts.tsx`, `Canvas.tsx`, `registry.tsx`, `store.ts`, new `ConditionalFormatDialog.tsx`, new drill/bookmark components, `RightPanel.tsx`
- Track 7: `WorkspaceDetail.tsx`, new `ModelView.tsx`, `RelationshipDialog.tsx`, `themes.ts`, `exportReport.ts`

**Risks**:

- Uncommitted Phase 2–5 / P0 work in this worktree must not be reverted. Track 0 confirms it before new edits.
- Upload must land in the dataset’s DuckDB and bump model version the same way SQL import does, or the field list will not refresh.
- Viewer must reuse `VisualRenderer` / `Charts.tsx` with a `readOnly` flag. Forking renderers will drift.
- Embed tokens are minted with a **service token**. The browser SDK must not call `POST /embed/token`.
- Cross-highlight that re-queries instead of dimming will feel like filter mode. Highlight is opacity only.
- Bookmarks persist inside the report JSON via auto-save (Task 2). They must not invent a new store.

**Assumptions**:

- Analysis and Plan in this file are the approval gate (AGENTS.md). Execution starts only after both are approved.
- MAGBI-010’s subtasks are Track 4 and Track 5. When those tracks run, update MAGBI-010’s execution log as well as this one.
- One single-sentence Conventional Commit per subtask. No commit until the user asks, unless they later say to commit as we go.
- Browser verification uses the GL dataset above. Credit card must show `1,973,281.93`.

**Jira Tasks**:

| Key | Summary |
|-----|---------|
| TASK-0 | Verify P0/P1 already in the tree |
| TASK-1 | Wells, card font, visual icons |
| TASK-2 | Excel/CSV upload |
| TASK-3 | DAX measure editor |
| TASK-4 | Read-only report viewer (MAGBI-010) |
| TASK-5 | Embed SDK and RLS UI (MAGBI-010) |
| TASK-6 | Slicer modes, highlight, conditional format, drill, bookmarks, tooltip well |
| TASK-7 | Members, model view, theme JSON, PDF/XLSX export |
| TASK-8 | Regression, DoD, PR |

---

## 2. Implementation Plan

Order: 0.1 → 1.1 → 1.2 → 1.3 → 2.1 → 2.2 → 3.1 → 3.2 → 4.1 → 4.2 → 4.3 → 5.1 → 5.2 → 5.3 → 6.1 → 6.2 → 6.3 → 6.4 → 6.5 → 6.6 → 7.1 → 7.2 → 7.3 → 7.4 → 8.1. Each subtask is code (if any) + test + browser check on GL. About 96 hours.

| Subtask Key | Summary | Acceptance Criteria | Est. | Status |
|-------------|---------|---------------------|------|--------|
| SUB-0.1 | GL regression | Card Credit is `1,973,281.93`. Tooltip is `40,365.75`. Y-axis uses `40K`. Edit then refresh restores the report. Rapid well drops do not freeze. Ctrl+A+Delete then Ctrl+Z restores all visuals. Right-click opens the menu. Five new visuals do not overlap | 2h | [x] |
| SUB-1.1 | Empty well placeholder | Empty wells are at least 40px, show “Drag field here”, and highlight on drag-over. A field drops on the first attempt | 2h | [x] |
| SUB-1.2 | Card auto-size | Default card is `360×180`. Short value uses a large font. `1,210,240.47` shrinks to fit. ResizeObserver updates font while resizing | 4h | [ ] |
| SUB-1.3 | Visual type icons | Insert tab: 13 distinct SVG icons ≥32×32, buttons ≥48×48, tooltip with the type name | 3h | [ ] |
| SUB-2.1 | Upload API | `POST /workspaces/{wid}/datasets/{did}/upload` accepts `.xlsx` or `.csv` multipart, writes a DuckDB table, updates definition columns/types, returns the new model | 5h | [ ] |
| SUB-2.2 | Get Data File tab | Get Data has File and Database tabs. Upload General-Ledger.xlsx → Ledger columns in the field list → a card of SUM Credit renders | 3h | [ ] |
| SUB-3.1 | Measure editor | Modeling → New Measure opens name, table, DAX. Save calls `POST .../definition/measures`. Invalid DAX shows the compiler error | 4h | [ ] |
| SUB-3.2 | Measures in field list | Measures show a calculator icon, drag to a card well, and the card shows the computed value | 2h | [ ] |
| SUB-4.1 | GET one report | `GET /workspaces/{wid}/reports/{rid}` returns name + definition. Embed token for another report is rejected. Unpublished report is hidden from embed | 3h | [ ] |
| SUB-4.2 | Viewer page | `/workspaces/:wid/reports/:rid/view` draws saved visuals, no ribbon or resize. Slicer and cross-filter work. Fit to page and fit to width scale the 1760×990 canvas | 5h | [ ] |
| SUB-4.3 | Open from reports list | Reports tab has View and Open in designer. View opens the named report (`?report=` is not required) | 2h | [ ] |
| SUB-5.1 | Embed host | `/embed/:reportId?token=` validates the token and renders the viewer with no MagBI chrome | 3h | [ ] |
| SUB-5.2 | Embed SDK | `embed(container, {reportId, accessToken, filters, pageName})` plus `setFilters`, `setPage`, `on('loaded'\|'error')`. Non-allowed origin is blocked. SDK does not mint tokens | 5h | [ ] |
| SUB-5.3 | RLS UI | Modeling: Manage roles (DAX filter per table) and View as (role + optional user, yellow banner). Visuals show only that role’s rows. Embed token with the role is restricted the same way | 6h | [ ] |
| SUB-6.1 | Slicer modes | List (current), Dropdown (single), Range (numeric/date min/max), Select All. Checking values still writes a page `in` filter | 4h | [ ] |
| SUB-6.2 | Cross-highlight | Highlight mode keeps all query rows and sets non-matching item opacity to 0.3. Filter mode still excludes. None ignores the source | 3h | [ ] |
| SUB-6.3 | Conditional format | Table color scale and rules (Approved/Pending/Rejected). Card color by value sign. Data bars in cells | 6h | [ ] |
| SUB-6.4 | Drill hierarchy | Hierarchy well. Double-click drills one level with a breadcrumb and an up control. Query uses the current level plus drill filters | 8h | [ ] |
| SUB-6.5 | Bookmarks | Capture page, filters, slicer selections, hidden visuals. Apply restores them. Auto-save persists bookmarks in the report JSON | 6h | [ ] |
| SUB-6.6 | Tooltip well | Extra fields in a Tooltips well appear in the formatted ECharts tooltip. Card tooltip style is a boxed layout | 3h | [ ] |
| SUB-7.1 | Members tab | Workspace detail has Members. List and invite (`GET/POST .../members`) | 3h | [ ] |
| SUB-7.2 | Model view | View → Model shows tables as boxes and relationship lines. Drag column to column opens the dialog. Save calls the existing relationships API | 8h | [ ] |
| SUB-7.3 | Theme JSON | Import Power BI theme JSON; data colors apply to every visual. Per-visual color still wins | 3h | [ ] |
| SUB-7.4 | Export files | PDF is a downloaded file (one landscape page per report page). Visual context menu Export data downloads filtered CSV/XLSX with a 150,000 row warning | 5h | [ ] |
| SUB-8.1 | Finalization | `tsc`, Vitest (`formatChart`, `pickReport`, `refreshPlan`, plus new tests), GL browser checklist below, this README’s execution log filled, PR description written | 2h | [ ] |

### Explicitly not in MAGBI-013

- Tasks 1–7, 11 except SUB-0.1 regression
- Rewriting WorkspaceList, DatasetWizard, RefreshPanel, GetDataDialog, InteractionEditor
- Tasks 31–35
- Sprint 11 ERP dashboard migration

### API contract for new/changed endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/workspaces/{wid}/reports/{rid}` | One report + definition (Track 4) |
| PUT | `/workspaces/{wid}/reports/{rid}` | Auto-save (already exists) |
| POST | `/workspaces/{wid}/datasets/{did}/query` | All visual queries |
| POST | `/workspaces/{wid}/datasets/{did}/upload` | Excel/CSV (Track 2) |
| POST | `/workspaces/{wid}/datasets/{did}/definition/measures` | Create measure (Track 3) |
| POST | `/embed/token` | Host-only token mint (Track 5) |
| POST | `/workspaces/{wid}/datasets/{did}/definition/relationships` | Model view save (existing; confirm path when implementing 7.2) |

### GL verification checklist (run after each track)

| After | Check |
|-------|--------|
| 0.1 | Credit card `1,973,281.93`; refresh keeps visuals |
| 1.x | Empty well placeholder; card font scales; Insert icons readable |
| 2.x | Upload xlsx → field list → chart |
| 3.x | `SUM(Ledger[Credit])` measure on a card |
| 4.x | View route has no ribbon; slicer still filters |
| 5.x | Iframe with token; View as HR hides other departments |
| 6.x | Drill Year→Month; bookmark restores slicer; highlight dims |
| 7.x | Model line between tables; PDF download; members invite |

---

## 3. Execution Log

- [x] SUB-0.1: 1501170
- [x] SUB-1.1: (pending)
- [ ] SUB-1.2: (Commit hash)
- [ ] SUB-1.3: (Commit hash)
- [ ] SUB-2.1: (Commit hash)
- [ ] SUB-2.2: (Commit hash)
- [ ] SUB-3.1: (Commit hash)
- [ ] SUB-3.2: (Commit hash)
- [ ] SUB-4.1: (Commit hash)
- [ ] SUB-4.2: (Commit hash)
- [ ] SUB-4.3: (Commit hash)
- [ ] SUB-5.1: (Commit hash)
- [ ] SUB-5.2: (Commit hash)
- [ ] SUB-5.3: (Commit hash)
- [ ] SUB-6.1: (Commit hash)
- [ ] SUB-6.2: (Commit hash)
- [ ] SUB-6.3: (Commit hash)
- [ ] SUB-6.4: (Commit hash)
- [ ] SUB-6.5: (Commit hash)
- [ ] SUB-6.6: (Commit hash)
- [ ] SUB-7.1: (Commit hash)
- [ ] SUB-7.2: (Commit hash)
- [ ] SUB-7.3: (Commit hash)
- [ ] SUB-7.4: (Commit hash)
- [ ] SUB-8.1: (Commit hash)

---

## 4. Definition of Done (DoD)

- [ ] Code is written and passes local tests and lints
- [ ] Single-sentence commit rule followed for all commits
- [ ] SSOT README is fully updated
- [ ] PR description generated from this checklist
- [ ] No rebuild of Tasks 1–7 / 11 / 20–24
- [ ] Excel upload works from Get Data on General-Ledger.xlsx
- [ ] Viewer route is read-only and uses the same visual renderers
- [ ] Embed SDK does not mint tokens; RLS View as restricts queries
- [ ] GL Credit card still shows `1,973,281.93` after all tracks
- [ ] MAGBI-010 execution log updated for Tracks 4–5

---

## 5. PR Description

_Filled at SUB-8.1._
