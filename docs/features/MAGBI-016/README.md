# Feature: MAGBI-016 - Power BI parity, proven on three MSD Warehouse dashboards

Source: MagBI Implementation Plan, Phase 6 (Tasks 50–56). Supersedes the build half of MAGBI-015: the W1 mockup (https://claude.ai/artifact/WydbiUV5DHc9o8wAWY6AeW) and spec are now built with the standard kit below.

## 1. Analysis

A code-verified parity matrix (Power BI vs MagBI, 30 Oct 2026) found the gaps that stop MagBI replacing the live dashboards. The ones that block the three Warehouse dashboards were fixed here; the rest stay in the plan (Phase 6 table and Tasks 38–49).

Defects found while building, all fixed in the platform:

| Defect | Effect before the fix |
|--------|----------------------|
| Relationship paths ignored direction | A filter on one fact leaked into another through a shared dimension and changed its numbers |
| Filters were applied only inside measures | A table of plain columns ignored every dropdown |
| The draft's `optional` filter matched columns by name and dropped filters silently | A filtered visual could show "All" totals with no warning |
| Validation rejected every star schema as "ambiguous" | The standard Power BI model shape could not be saved |
| SQL query tables were refused at refresh | Datasets could not be built on read-only ERP queries |
| Uploaded tables were dropped by a refresh | Mixed datasets lost data |
| Dev credential key changed at every start | Saved connections broke after a restart |
| Windows briefly locks a freshly written dataset file | Uploads failed intermittently |
| KPI status was set by hand | Colour and glyph could contradict the value |
| Visuals guessed column roles from names | A renamed column silently broke a visual |

## 2. What was built

| Task | Delivered |
|------|-----------|
| 50 Native SQL datasets | `SqlQuerySource` imported at refresh behind a read-only guard; `describe_query` for SQL Server; uploads carried through a refresh; persistent dev key; retry on Windows file locks |
| Engine | Filters flow one way (one side to many side) and reach detail rows; a filter that cannot reach a visual is reported (`ignoredFilters`) and shown as "Not filtered by …"; validation and joins follow filter direction |
| 52 Status and theme | One tone rule (blank / zero / ordered steps / otherwise) drives colour, glyph and word; ERP Native tokens; page background from the theme |
| 53 Standard kit | `web/src/kit`: header, label, frame, KPI card, chain, period columns (every member, colour rule), donut (centre = slices, legend table), Pareto, heat matrix, status table (sort, top N, formats, pills), target gauge, ranked bars, 100% stacked bar, stage flow; empty and error states; report dropdowns without blank options |
| 55 QA gate | `server/scripts/qa_gate.py`: static, live (every visual × every filter value, figures against MSD_ERP) and render checks in headless Chrome at 1920 × 1080, repeated for every dropdown value |
| 56 Build library | `server/scripts/magbi_lib.py` (frame layouts A and B, standing rules, API) and `server/scripts/wms/` (read-only extract, model, W1/W4/W7 builders, independent truth figures) |

Rebuild everything: `MAGBI_MSD_ENV=<.env.db> python -m scripts.wms.build_wms --workspace <id>`, then `python -m scripts.qa_gate ...`.

## 3. The loop

| Round | Result | Fixed in the platform or the gate |
|-------|--------|-----------------------------------|
| 1 | 3 FAIL | Queries "slow" (2.1 s) — the gate's `localhost` lookup on Windows, not MagBI (0.04 s by IP); donut centre measured on the figure alone; by eye: KPI bottom line touching the edge, Pareto 80% labels colliding, "100%" shown for 99.5% |
| 2 | 3 FAIL | Every KPI card 1 px taller than its box (the canvas frame kept a 1.5 px border on kit visuals) |
| 3 | W4, W7 PASS; W1 PASS with one by-eye fix | Pareto 80% label sat on the first bar; the dashed line already meets the right axis 80% tick, so the label was removed |
| 4 | W1 PASS | |

Final: every dashboard passes. 341 queries across 31 filter contexts, the slowest 0.19 s; 17 headline figures equal MSD_ERP; 31 renders at 1920 × 1080 with no clipped text, blanks, NaN, empty panels or off-centre donuts. Screenshots in `screenshots/`. Two tables scroll inside their panel by design (top 25, all requests).

## 4. Mockup and spec comparison (W1 against the mockup; W4 and W7 against the approved redesign spec)

| Panel | Built | Note |
|-------|-------|------|
| Header, data as at, units | Same | "Data as at" is the dataset's last change |
| Filter box, 2 dropdowns, 7-step chain | Same | Inbound, Quality and Dispatch have no warehouse in the ERP; their tooltips say so |
| 5 KPI cards | Same rules and words | Value 24 px (frame spec) where the mockup drew 28 px |
| When stock expires | Same | Every month present, zeros included; next 90 days amber |
| Batches by storage class | Same | No-data member listed last |
| Pareto, heat matrix, expiring soonest | Same | Top 25 scrolls inside its panel, as specified |
| W4 gauge, 100% bar, movement bars, coverage donut, variances table | Same | Controlled-drug variances cannot fire: the ERP flag is unset |
| W7 stage flow, status donut, on-time gauge, activity bars, requests table | Same | On-time uses shipped deliveries; shows "–" until something ships |

## 5. Decisions and open items

- Confirmed by the owner on 31 Oct 2026: W7 on-time is measured against shipped deliveries; W4 count coverage is On track at 90% or more.
- The MSD_ERP connection: build runs use a read-only snapshot; switching tables to the live connection needs the credential entered once in MagBI.
- Login, embedding (Tasks 38–39) and the remaining parity rows before ERP go-live.

## 6. Definition of Done

- [x] All three dashboards pass the QA gate
- [x] Figures equal MSD_ERP
- [x] No stand-in visuals
- [x] Read-only SELECTs on MSD_ERP only
- [x] Tests for new behaviour; full pytest and Vitest pass
- [x] Single-sentence commits
