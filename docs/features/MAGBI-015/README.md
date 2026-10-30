# Feature: MAGBI-015 - Warehouse: Stock & Expiry, the first native MagBI dashboard

Source: mockup and build spec "MagBI Stock & Expiry" (https://claude.ai/artifact/WydbiUV5DHc9o8wAWY6AeW). Top half is the design, bottom half the spec (sections 1–9). The design and colours are fixed; this ticket builds them, it does not redesign them.

## 1. Analysis

### Data (checked read-only on MSD_ERP, 30 Oct 2026)

- Every table and column in the spec's queries exists: `wms.SKUBatch`, `wms.SKU`, `veims.ItemMaster` (incl. `Refrigeration`, `IsControlledSubstance`, `StorageTemperature`, `StorageRule`), `wms.StockOnHand` (`WareHouseGuid`, `BatchGuid`), `wms.WareHouse`.
- Live figures today: **1,461** batches on hand, **274** expiring in 90 days, **0** expired, **6** without expiry. The mockup's 25 Oct figures (1,455 / 263 / 0 / 6) have moved with the data, so acceptance test 1 compares against SQL at test time, not the mockup's fixed numbers.
- **FEFO source**: the spec says "veims item issue", but no such table exists. The live Power BI WMS-Model uses `veims.ItemWithdrawals` (`ItemGuid`, `BatchNbr`, `WithDrawalDate`) for its `FEFO breaches` measure. This ticket uses the same source and rule (an item + batch pair issued while an older-expiring batch of that item was on hand).
- **Chain counts**: reuse the `Stock flow stage` queries from the live WMS-Model, as the spec asks.
- Refresh accepts whole SQL tables only. `SqlQuerySource` is rejected with "not importable yet", so this pass loads a CSV snapshot of the read-only queries. The saved connection is `MSD_ERP` (`429bb999-e3df-4a3d-a39b-e769ab424342`).

### Model

| Table | Grain | Key columns |
|-------|-------|-------------|
| Batch | batch × warehouse it has stock in (no warehouse = one row, blank warehouse) | BatchID, Item, Category, Storage class, Expiry date, Expiry month, Days left, Window, Qty on hand, Warehouse |
| Month | every month from the current month to the last expiry month | Month (first day), Label "Nov 26", In next 90 days |
| Chain | stage × warehouse | Stage, Order, Count, Unit, Tone, Highlight |
| FEFO | breaching item + batch pair × warehouse | Pair, Warehouse, Category |
| Stock line | stock line × warehouse | for the "1,468 stock lines · 1,541 SKUs" context |

Batches are counted with `DISTINCTCOUNT(Batch[BatchID])`, so a batch held in two warehouses counts once under "All" and once in each warehouse. That matches the spec's rule that a batch belongs to every warehouse it has a stock line in. All measures fit DAX-lite (`DISTINCTCOUNT`, `CALCULATE`, filters). Days left and Window are computed at refresh with `GETDATE()`, so the dataset must refresh at least daily.

### What MagBI can draw today

| Mockup panel | MagBI today | Gap to close |
|--------------|-------------|--------------|
| Header (breadcrumb, title, question, data as at) | Nothing. The Text box button does nothing | Header visual |
| Warehouse and Category dropdowns | Slicer, dropdown mode | Hide blank option; check cross-table filtering |
| 7-step stock-flow chain | Nothing | Chain visual |
| 5 KPI cards with status edge, glyph + word, context line | Plain card | KPI status card |
| When stock expires (every month, amber next 90 days, labels over 0) | Column chart | Show months with no data; colour rule by category; hide zero labels; plain-word tooltip |
| Donut with total in the hole and a legend table | Pie | Donut ring, centred total, legend table, fixed grey for "Not recorded" |
| Pareto (bars + cumulative % line, 80% reference) | Nothing (no combo) | Pareto visual |
| Expiry window by category heat matrix | Table with fixed colour scale | Heat matrix visual |
| Expiring soonest (top 25, pills) | Table | Sort, top N, date format, status pill rule |
| Panel title strip and subtitle, ERP Native theme | Title and background only | Panel chrome and theme preset |
| Empty state "Nothing recorded for this view yet" | Blank panel | Empty state in every visual |

Every gap here recurs across the other 54 dashboards (chain, KPI status cards, donut totals, Pareto, heat matrices, pills), so each is built as a reusable MagBI visual or option, not a one-off.

**Affected files**: `web/src/designer/visuals/registry.tsx`, `catalog.ts`, `Charts.tsx`, `formatChart.ts`, new visual components under `web/src/designer/visuals/`, `web/src/shared/themes.ts`, `server/magbi/engine/` (months with no data), a build script `server/scripts/build_stock_expiry.py`, tests beside each.

**Risks**:

- Showing months with no data needs the query engine to keep dimension rows that have no facts. If it can't today, that is an engine change.
- Credentials: I can't enter the MSD_ERP password. The owner creates the MSD_ERP connection in MagBI once. Until then the build is verified on a snapshot from the same read-only queries, loaded through the upload API, with the same table shapes.
- The dev server generates a new credential key at every start, so a saved connection breaks after a restart. Persist the dev key in the gitignored `server/data/` folder.

**Jira Tasks**:

| Key | Summary |
|-----|---------|
| TASK-1 | Parameters, report filters, calculated fields, formats, sort, fill |
| TASK-2 | Theme, frame, panel, header |
| TASK-3 | KPI, chain, donut, Pareto, heat matrix, gauge, table |
| TASK-4 | Empty and error states |
| TASK-5 | Publish QA |
| TASK-6 | Rebuild Stock & Expiry and pass the 9 acceptance tests |

---

## 2. Implementation Plan

Source of this order: the 30 Oct 2026 designer pass at 1920×1080 (1 of 9 acceptance tests passed). Each finding names the platform feature that fixes it. Features are reusable across dashboards, not one-off widgets. One single-sentence commit per subtask. Do not invent the stock-flow SQL; the WMS-Model stage queries are not in this repo.

Already in the tree, do not rebuild: month-label sort and zero-fill (`period.ts`), whole-number value format, "Couldn't load" on a failed query, slicer mode hidden in the viewer, `COUNT` / `DISTINCTCOUNT` on text keys in the compiler (the running API still has the old rule until restart).

### TASK-1 — Data and filtering

Fixes A1–A3 and B1–B6.

| Subtask | Summary | Acceptance criteria | Status |
|---------|---------|---------------------|--------|
| SUB-1.1 | Parameterised SQL | A dataset table can be a read-only `SELECT` with `@warehouse` and `@category`. Null means All. Refresh runs it. A category filter no longer returns `NO_RELATIONSHIP` | [ ] |
| SUB-1.2 | Report filters | Warehouse and Category are report-level filters. Options come from a query and never include a blank. Every widget that uses the parameter re-queries, including the heat matrix and the soonest list | [ ] |
| SUB-1.3 | Calculated fields | A field declares its aggregation (`distinctCount`, `count`, `sum`). "Batches on hand" is a distinct count of the batch id, a whole number, equal to SQL (1,461 with no filter; 737 for Pharmaceuticals; 1,459 for Central Warehouse 2). It is not a sum of unrelated KPI rows | [ ] |
| SUB-1.4 | Formats | Number format: whole, decimals, %, thousands separator, K/M/bn, prefix, suffix. Date format: `dd Mon yyyy`, `Mon yy`. A raw key can have a display label | [x] |
| SUB-1.5 | Sort and missing periods | A widget sorts by value, by label, or by a sort column. A time axis fills every period in the range with 0. `Dec 26` comes before `Jan 28`. Apr–Sep 27 are present as 0 | [x] |
| SUB-1.6 | Cross-filter and errors | Clicking a bar, slice, or row filters the other widgets; a second click clears it. A failed query shows "Couldn't load: <reason>" in the panel. The List/Dropdown/Range picker is a designer setting | [ ] |

### TASK-2 — Theme and layout

Fixes C3–C5 and D3.

| Subtask | Summary | Acceptance criteria | Status |
|---------|---------|---------------------|--------|
| SUB-2.1 | Theme file | One token set: page `#EEF2F7`, panel `#FFFFFF`, title strip `#E9EEF5`, line `#D3DCE6`, ink `#22324A`, muted `#66758A`, data 1–4, and good / watch / action / no-data / information with their inks. Components read tokens. Nothing is coloured by hand | [x] |
| SUB-2.2 | Canvas | The page is 1760×990 on a snap grid. At 1920×1080 the dashboard does not scroll inside itself. A visual past the canvas is a design error, not a scrollbar | [ ] |
| SUB-2.3 | Panel frame | Title strip: title on the left, subtitle on the right. The subtitle truncates first. The legend never covers the title. A table fills at least 90% of the panel width and wraps headers without breaking a word | [ ] |
| SUB-2.4 | Header | Breadcrumb, title, question, "Data as at" (query time), and the units line. No ribbon on the published page | [x] |

### TASK-3 — Standard visuals

Fixes C1, C2, D1, D2, E1, E2, F1, F2, and G2.

| Subtask | Summary | Acceptance criteria | Status |
|---------|---------|---------------------|--------|
| SUB-3.1 | KPI card | Caption, value, glyph + word, context line, 3 px status edge. Watch if expiring or missing expiry is > 0. Action if expired or FEFO is > 0. A blank value prints "–" | [x] |
| SUB-3.2 | Chain | Seven boxes: count, unit, glyph, status underline. Storage is highlighted on this page. Filtered by warehouse. Status keys (`good`, `watch`, `action`, `none`, `info`) map to colour + glyph + word. Blocked until the WMS-Model stage SQL is supplied | [ ] |
| SUB-3.3 | Donut | Ring inner radius about 62%. The centred total equals the sum of the visible slices, within 2 px. Legend table beside the ring: dot, name, count, share. "Not recorded", "Not set", "Unknown", "None", and blank are grey `#9EABBC` | [x] |
| SUB-3.4 | Pareto | One visual: bars sorted largest first, cumulative line on a 0–100% axis, dashed 80% reference line. Reference lines are available on any axis | [x] |
| SUB-3.5 | Heat matrix | A pivot of category × window, not a long list. Blue intensity by value. The ≤ 90 day column uses the action hue. Zero is "–" on `#F3F6FA`. Headers do not break mid-word | [x] |
| SUB-3.6 | Table | Fills the panel. Dates render as `dd Mon yyyy`. Days left is a pill: action ≤ 30, watch ≤ 90. Numbers are right-aligned and tabular. Sort is per widget. Top 25 scrolls | [ ] |
| SUB-3.7 | Gauge | Value against a target, status-coloured figure, a "◆ Watch · Target 95%" line, "–" when there is no data. Not on this dashboard; built so the next one can use it | [ ] |

### TASK-4 — Empty and error states

| Subtask | Summary | Acceptance criteria | Status |
|---------|---------|---------------------|--------|
| SUB-4.1 | Empty | No rows shows "Nothing recorded for this view yet", centred. A blank white panel is a defect | [x] |
| SUB-4.2 | Error | A failed query shows "Couldn't load: <reason>" and the same text is available in a log. A 422 is not only a browser console line | [x] |

### TASK-5 — Publish QA

| Subtask | Summary | Acceptance criteria | Status |
|---------|---------|---------------------|--------|
| SUB-5.1 | QA gate | Publish runs the six checks below. A failure blocks publish and the check report is saved with the report | [ ] |

Checks: every widget runs with no filter and with every filter value (no error, no blank KPI or centre, no NaN); nothing sits outside the canvas, overlaps, clips, or scrolls inside a panel, and tables are at least 90% of the panel width; each donut total equals its slices, is centred, and greys no-data members; status is always glyph + word; only theme tokens are used; each query is under 2 s.

### TASK-6 — Rebuild Stock & Expiry

| Subtask | Summary | Acceptance criteria | Status |
|---------|---------|---------------------|--------|
| SUB-6.1 | Report | `build_stock_expiry.py` creates the dataset and the report through the API from the live read-only queries. The page matches the mockup layout: header, two filters, chain, five KPIs, expiry calendar, donut, Pareto, heat matrix, soonest list | [ ] |
| SUB-6.2 | Acceptance | Spec section 8, tests 1–9, each pass/fail with a screenshot at 1920×1080. Figures match SQL at test time (the 25 Oct mockup numbers have moved). Test 9: each query under 2 s | [ ] |

Order: 1.1 → 1.2 → 1.3 → 1.4 → 1.6 → 2.1 → 2.2 → 2.3 → 2.4 → 3.1 → 3.3 → 3.4 → 3.5 → 3.6 → 3.2 → 3.7 → 4.1 → 4.2 → 5.1 → 6.1 → 6.2. SUB-1.5 is done. SUB-3.2 waits on the stage SQL and does not block the other visuals.

---

## 3. Execution Log

- [ ] SUB-1.1: Live extract loaded as dataset `cc99b271-a756-4dd5-b17b-560c215160ed` (Batch 1,462 rows / 1,461 ids, Month 31, StockLine 1,479, FEFO 0). Queries each ran in under 2 s. `COUNTROWS(StockLine)` = 1,479 and `COUNTROWS(Batch)` = 1,462. `DISTINCTCOUNT` on `BatchID` is rejected because the id is text. Chain is not loaded: no stock-flow view exists, and the WMS-Model stage SQL is not in this repo.

---

## 4. Definition of Done (DoD)

- [ ] Every acceptance test in spec section 8 passes, with screenshots
- [ ] Panel-by-panel match with the mockup; no stand-in visuals
- [ ] Only read-only SELECTs on MSD_ERP; no other database touched
- [ ] New visuals and options have tests; full pytest and Vitest pass
- [ ] Single-sentence commit rule followed for all commits
