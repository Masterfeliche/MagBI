# Sprint 11: Integration & Migration — Detailed Implementation Plan

**Sprint:** 11 of 11
**Timeline:** Week 15–16 (final sprint of Phase 1)
**Milestone:** 4 — Production migration complete
**Prerequisite:** Sprints 1–10 complete (query engine, designer, viewer, auth, refresh all operational)

---

## Objective

Migrate all 55 ERP dashboards from Power BI to MagBI. When this sprint is
done, every dashboard that currently runs through Power BI Embedded runs
natively through MagBI, and Power BI can be decommissioned.

---

## Preconditions Checklist

Before starting this sprint, verify:

- [ ] MagBI query engine handles all semantic queries (Sprint 5)
- [ ] DAX-lite compiler covers all functions used in production dashboards (Sprint 4)
- [ ] Report designer can create and publish reports (Sprint 9)
- [ ] Embed SDK renders reports inside iframes with theme sync (Sprint 10)
- [ ] Auth system issues embed tokens from service tokens (Sprint 7)
- [ ] Scheduled refresh runs reliably with zero-downtime swap (Sprint 8)
- [ ] Transform engine folds queries correctly (Sprint 6)
- [ ] SQL Server connector imports data from MSD_ERP (Sprint 2)

---

## Task Breakdown

### Task 11.1: Power BI Report Definition Parser

**Goal:** Read existing Power BI `.pbix` files and extract report definitions
into a structured format that can be converted to MagBI report JSON.

**Context:** A `.pbix` file is a ZIP archive containing:
- `Report/Layout` — JSON defining pages, visuals, positions, and bindings
- `DataModelSchema` — JSON defining the semantic model (tables, relationships, measures)
- `DiagramLayout` — JSON defining the model diagram view

**Subtasks:**

| # | Subtask | File | Description |
|---|---------|------|-------------|
| 11.1.1 | PBIX extractor | `scripts/migration/pbix_reader.py` | Open `.pbix` as ZIP, extract `Report/Layout` and `DataModelSchema` JSON |
| 11.1.2 | Model mapper | `scripts/migration/model_mapper.py` | Convert Power BI DataModelSchema → MagBI DatasetDefinition JSON. Map tables, columns, relationships, and measures. |
| 11.1.3 | Visual mapper | `scripts/migration/visual_mapper.py` | Convert Power BI visual definitions → MagBI report definition JSON. Map visual types (clusteredBarChart → bar, lineChart → line, card → card, tableEx → table, etc.), positions, sizes, field bindings. |
| 11.1.4 | Filter mapper | `scripts/migration/filter_mapper.py` | Convert Power BI filter definitions (page filters, visual filters, slicers) → MagBI filter pane configuration. |
| 11.1.5 | Theme mapper | `scripts/migration/theme_mapper.py` | Extract Power BI report theme (colours, fonts) and map to MagBI theme tokens. Where possible, map to the official MSD Enterprise theme. |

**Acceptance criteria:**
- Given any of the 55 `.pbix` files, the parser produces valid MagBI JSON
- Visual positions and sizes are preserved (scaled to 1760×990 canvas)
- All field bindings (values, axis, legend, tooltips) are mapped correctly
- Unmappable visuals or DAX functions are logged with file and visual ID

**Notes for agent:**
- The 55 `.pbix` files live in `BI-DASHBOARDS-OFFICIAL/` on the ERP build machine
- Power BI visual type names differ from MagBI names — build a lookup table
- Power BI positions are in a coordinate system that may need scaling
- Some visuals may use custom visuals — log these as unsupported and provide a fallback

---

### Task 11.2: DAX Compatibility Audit

**Goal:** Verify that every DAX function and pattern used across all 55
dashboards is supported by MagBI's DAX-lite compiler.

**Subtasks:**

| # | Subtask | File | Description |
|---|---------|------|-------------|
| 11.2.1 | DAX extractor | `scripts/migration/dax_extractor.py` | Walk all 55 `.pbix` DataModelSchema files, extract every DAX measure expression and calculated column expression |
| 11.2.2 | Function inventory | `scripts/migration/dax_inventory.py` | Parse each DAX expression, extract function calls, build a frequency table: function name → count → list of dashboards that use it |
| 11.2.3 | Compatibility checker | `scripts/migration/dax_checker.py` | Compare the inventory against MagBI's `dax/functions.py` supported function list. Output: supported (green), partially supported (yellow), unsupported (red) |
| 11.2.4 | Gap report | `docs/migration/DAX-COMPATIBILITY-REPORT.md` | Document every unsupported function, how many dashboards use it, and the recommended action (implement, rewrite, or accept limitation) |
| 11.2.5 | Gap implementation | `server/magbi/dax/functions.py` | Implement any missing DAX functions that are used in 3+ dashboards. Functions used in only 1–2 dashboards can be rewritten as alternative expressions. |

**Acceptance criteria:**
- Every DAX expression across all 55 dashboards is parsed without error
- 100% of functions used in 3+ dashboards are supported
- A compatibility report exists documenting any gaps and workarounds
- Rewritten expressions produce identical results to the original DAX

**DAX functions expected in MSD ERP dashboards (based on build history):**
- Aggregation: `SUM`, `COUNT`, `COUNTROWS`, `AVERAGE`, `MIN`, `MAX`, `DISTINCTCOUNT`
- Logic: `IF`, `SWITCH`, `AND`, `OR`, `NOT`, `ISBLANK`, `COALESCE`
- Filter: `CALCULATE`, `CALCULATETABLE`, `ALL`, `ALLEXCEPT`, `FILTER`, `VALUES`
- Time intelligence: `SAMEPERIODLASTYEAR`, `DATEADD`, `TOTALYTD`, `TOTALMTD`, `DATESYTD`, `DATESMTD`, `PREVIOUSMONTH`, `PREVIOUSYEAR`
- Table: `SUMMARIZE`, `ADDCOLUMNS`, `SELECTCOLUMNS`, `TOPN`, `UNION`
- Text: `CONCATENATE`, `FORMAT`, `LEFT`, `RIGHT`, `LEN`, `UPPER`, `LOWER`, `TRIM`
- Math: `DIVIDE`, `ABS`, `ROUND`, `INT`, `MOD`
- Relationship: `RELATED`, `RELATEDTABLE`, `USERELATIONSHIP`

---

### Task 11.3: Batch Migration Script

**Goal:** A single script that migrates all 55 dashboards end-to-end.

**Subtasks:**

| # | Subtask | File | Description |
|---|---------|------|-------------|
| 11.3.1 | Migration orchestrator | `scripts/migration/migrate_all.py` | For each `.pbix` file: (1) parse it, (2) create/update the MagBI dataset definition, (3) create the MagBI report definition, (4) trigger a data refresh, (5) publish the report, (6) log the result |
| 11.3.2 | Validation pass | `scripts/migration/validate_migration.py` | For each migrated dashboard: (1) load it in MagBI viewer, (2) verify all visuals render, (3) compare visual count and types against the source, (4) flag any visual that errors |
| 11.3.3 | Migration manifest | `docs/migration/MIGRATION-MANIFEST.md` | Table of all 55 dashboards: source `.pbix` filename, MagBI report ID, module, status (migrated/partial/failed), notes |
| 11.3.4 | Rollback capability | `scripts/migration/rollback.py` | Given a dashboard name, revert the ERP registry entry to point back to Power BI. This is the safety net during parallel-run. |

**Acceptance criteria:**
- `python migrate_all.py --source /path/to/pbix/ --target http://magbi-api` migrates all dashboards
- Each dashboard is logged with pass/fail and error details
- The manifest is auto-generated with migration status per dashboard
- Rollback works per-dashboard (not all-or-nothing)

**Module-to-dashboard mapping (55 dashboards):**

| Module | Dashboard Count | Notes |
|--------|----------------|-------|
| Finance | 5 | Revenue, expenses, cash flow, budget variance, treasury |
| HR | 8 | Workforce, hiring desk, attendance, leave, recruitment, roster, payroll, headcount |
| Procurement | 8 | Spend analysis, PO tracking, vendor performance, contract, inventory |
| Transport | 9 | Fleet availability, fuel, maintenance, trips, driver, route, compliance, utilisation, cost |
| Sales | 6 | Pipeline, revenue, wallet, GePG, MOU, targets |
| CRM | 8 | Tickets, SLA, agent performance, satisfaction, backlog, escalation, resolution, overview |
| WMS | 7 | Stock levels, inbound, outbound, locations, picking, cycle count, aging |
| PME | 4 | Asset register, maintenance schedule, utilisation, depreciation |

---

### Task 11.4: ERP Dashboard Registry Integration

**Goal:** Update the ERP's `vecfg.BiDashboard` table to point to MagBI
instead of Power BI.

**Subtasks:**

| # | Subtask | File | Description |
|---|---------|------|-------------|
| 11.4.1 | Registry update script | `scripts/migration/update_registry.py` | For each migrated dashboard: update `vecfg.BiDashboard` to set the embed URL to `https://<magbi-host>/embed/<report-slug>` instead of the Power BI embed URL |
| 11.4.2 | Embed endpoint configuration | `scripts/migration/configure_embed.py` | Set the ERP's MagBI service token, embed base URL, and theme configuration in the ERP's application settings |
| 11.4.3 | Security object mapping | `scripts/migration/map_security.py` | For each module, verify that the ERP Security Object (e.g., "Finance Pages", "HR Pages") grants access to the MagBI dashboard URL at `/bi-analytics/<slug>` |
| 11.4.4 | Parallel-run toggle | `scripts/migration/parallel_run.py` | A toggle that lets individual dashboards switch between Power BI and MagBI. During the parallel-run period, department heads compare both side by side. |

**Acceptance criteria:**
- ERP navigation (e.g., Finance → Analytics) opens MagBI instead of Power BI
- Security objects correctly control access per module
- Parallel-run toggle works per-dashboard for A/B comparison
- No changes to the ERP's frontend code — only registry data and embed config

**ERP integration details:**
- The ERP opens dashboards at `/bi-analytics/<slug>` (see `vecfg.BiDashboard` table)
- The ERP's embed page uses `powerbi.embed` with `BackgroundType.Transparent`
- MagBI's embed SDK must handle the same iframe communication pattern
- The ERP issues a service token; MagBI exchanges it for an embed token with user attributes

---

### Task 11.5: ERP Navigation Integration

**Goal:** Enable click-through from MagBI dashboard visuals to ERP pages.

**Subtasks:**

| # | Subtask | File | Description |
|---|---------|------|-------------|
| 11.5.1 | Navigation event spec | `docs/migration/NAV-EVENTS.md` | Document every drill-through and click action across the 55 dashboards. Format: dashboard → visual → click target (ERP page URL + parameters). |
| 11.5.2 | SDK navigation handler | `web/src/embed/sdk.ts` | Implement `onVisualClicked` callback in the embed SDK. When a visual is clicked, emit an event with the target entity type, ID, and suggested ERP URL. |
| 11.5.3 | ERP-side handler | `scripts/migration/erp_nav_handlers.md` | Document the ERP-side JavaScript that listens for MagBI SDK events and navigates to the correct ERP page (e.g., clicking a vendor name → `/procurement/vendors/{id}`). |
| 11.5.4 | Navigation mapping table | `scripts/migration/nav_mapping.json` | JSON mapping: `{ "entity_type": "vendor", "erp_url_template": "/procurement/vendors/{VendorId}" }` for all entity types used in dashboard click-throughs. |

**Acceptance criteria:**
- Clicking a vendor name in a procurement dashboard navigates to the vendor's ERP page
- Clicking an employee name in an HR dashboard navigates to the employee's ERP profile
- Clicking a transaction in a finance dashboard navigates to the transaction detail
- Navigation works through the embed SDK event system, not hard-coded URLs

**Known entity types in MSD ERP dashboards:**
- Vendor → `/procurement/vendors/{VendorId}`
- Employee → `/hr/employees/{EmployeeId}`
- Invoice → `/finance/invoices/{InvoiceId}`
- Purchase Order → `/procurement/purchase-orders/{PurchaseOrderId}`
- Vehicle → `/transport/fleet/{VehicleId}`
- Warehouse Item → `/wms/items/{ItemId}`
- Customer → `/crm/customers/{CustomerId}`
- Ticket → `/crm/tickets/{TicketId}`
- Asset → `/pme/assets/{AssetId}`

---

### Task 11.6: End-to-End Testing

**Goal:** Validate every migrated dashboard with real data and real RLS.

**Subtasks:**

| # | Subtask | File | Description |
|---|---------|------|-------------|
| 11.6.1 | Test plan per module | `docs/migration/E2E-TEST-PLAN.md` | For each module: list every dashboard, every visual, and the expected behaviour (data loads, filters work, cross-filter works, drill-through works, RLS restricts correctly) |
| 11.6.2 | RLS test matrix | `scripts/migration/rls_test_matrix.py` | Generate a test matrix: for each dashboard × each RLS role (department, branch, cost centre), verify the user sees only their data. Use 3 test users with different permission sets. |
| 11.6.3 | Visual comparison script | `scripts/migration/visual_compare.py` | For each dashboard: query both Power BI and MagBI with the same filters, compare the result sets. Flag any numeric difference > 0.01%. |
| 11.6.4 | Cross-filter test | `scripts/migration/crossfilter_test.py` | For each dashboard: programmatically click each slicer value and verify all visuals update. Use the embed SDK's filter API. |
| 11.6.5 | Refresh reliability test | `scripts/migration/refresh_test.py` | Trigger 10 consecutive refreshes for each dataset. Verify all succeed, old data stays live during refresh, and the timestamp updates. |

**Acceptance criteria:**
- All 55 dashboards render all visuals without errors
- Data matches Power BI output within 0.01% tolerance
- RLS correctly restricts data for 3 test user profiles
- Cross-filtering works on every slicer across all dashboards
- 10/10 refresh cycles succeed per dataset

---

### Task 11.7: Performance Profiling

**Goal:** Verify MagBI meets the < 3 second p90 dashboard load time target.

**Subtasks:**

| # | Subtask | File | Description |
|---|---------|------|-------------|
| 11.7.1 | Load time benchmark | `scripts/migration/benchmark_load.py` | For each dashboard: measure time from embed SDK `init()` to `loaded` event, 50 runs. Record p50, p90, p99. |
| 11.7.2 | Query time breakdown | `scripts/migration/benchmark_queries.py` | For each dashboard: measure each semantic query's execution time. Identify the slowest query per dashboard. |
| 11.7.3 | Optimisation pass | — | For any dashboard with p90 > 3s: add missing indexes to DuckDB, add query cache warming, simplify expensive DAX measures, or pre-aggregate. |
| 11.7.4 | Performance report | `docs/migration/PERFORMANCE-REPORT.md` | Table of all 55 dashboards with load times (p50/p90/p99), query count, slowest query, and whether the < 3s target is met. |

**Acceptance criteria:**
- 90% of dashboards load in < 3 seconds (p90)
- No dashboard loads slower than 5 seconds (p99)
- A performance report documents every dashboard's metrics
- Any optimisations are documented for future reference

---

## Execution Order

```
Week 15:
  Day 1–2:  Task 11.2 (DAX audit) + Task 11.1 (PBIX parser) — in parallel
  Day 3:    Task 11.2.5 (implement missing DAX functions)
  Day 4–5:  Task 11.3 (batch migration script) + run migration

Week 16:
  Day 1:    Task 11.4 (ERP registry integration)
  Day 2:    Task 11.5 (navigation integration)
  Day 3–4:  Task 11.6 (end-to-end testing)
  Day 5:    Task 11.7 (performance profiling) + fixes
```

**Parallel-run period:** After the migration, run both Power BI and MagBI
for 1–2 weeks. Department heads compare dashboards side by side. Only
decommission Power BI after all 8 module owners sign off.

---

## Files Created by This Sprint

```
scripts/migration/
├── pbix_reader.py
├── model_mapper.py
├── visual_mapper.py
├── filter_mapper.py
├── theme_mapper.py
├── dax_extractor.py
├── dax_inventory.py
├── dax_checker.py
├── migrate_all.py
├── validate_migration.py
├── rollback.py
├── update_registry.py
├── configure_embed.py
├── map_security.py
├── parallel_run.py
├── rls_test_matrix.py
├── visual_compare.py
├── crossfilter_test.py
├── refresh_test.py
├── benchmark_load.py
├── benchmark_queries.py
└── nav_mapping.json

docs/migration/
├── DAX-COMPATIBILITY-REPORT.md
├── MIGRATION-MANIFEST.md
├── NAV-EVENTS.md
├── E2E-TEST-PLAN.md
└── PERFORMANCE-REPORT.md
```

---

## Definition of Done

- [ ] All 55 dashboards migrated and rendering in MagBI
- [ ] Data matches Power BI output within 0.01% tolerance
- [ ] RLS verified for 3 test user profiles across all modules
- [ ] Cross-filtering works on every dashboard
- [ ] Navigation click-throughs work for all entity types
- [ ] ERP registry points to MagBI for all 55 dashboards
- [ ] p90 load time < 3 seconds for 90% of dashboards
- [ ] Rollback script tested and documented
- [ ] Parallel-run toggle operational
- [ ] Department head sign-off per module
- [ ] Performance report generated
- [ ] Migration manifest complete with status per dashboard
