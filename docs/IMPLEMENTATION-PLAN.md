# MagBI Implementation Plan

**Version:** 1.0
**Date:** 29 October 2026
**Aligned to:** SRS Phase 1 (Milestone 1–4, 16 weeks)

---

## Current State

The project has:
- Full architecture specs (8 documents, ~8,500 lines)
- SRS with 94 functional requirements
- 11-chapter knowledge base
- Scaffolded server (9 Python packages, all placeholder modules)
- Scaffolded web (types, store, registry, SDK — all stubs)
- Docker Compose, CI workflow, AI workflow system

**Nothing runs yet.** Every `.py` and `.ts` file beyond `main.py`, `config.py`,
and `base.py` is an empty placeholder. The implementation starts here.

---

## Principles

1. **Vertical slices.** Each sprint delivers a working feature end-to-end
   (server + web + test), not a horizontal layer.
2. **Milestone 1 first.** The query engine is the foundation — nothing else works
   without it. We build bottom-up: storage → connectors → model → engine → API.
3. **One package at a time.** Each sprint focuses on one server package. Tests
   ship with the code, not after.
4. **Real data early.** By Sprint 3, we connect to MSD_ERP and run real queries.
5. **AI agents can pick up any sprint.** Each sprint below is a self-contained
   feature request that an agent can execute using the AGENTS.md workflow.

---

## Sprint Plan

### Sprint 1: Foundation (Week 1–2)

**Goal:** The server starts, connects to PostgreSQL, and serves health checks.

| # | Task | Package | Files | FR |
|---|------|---------|-------|-----|
| 1.1 | PostgreSQL metadata models (SQLAlchemy/SQLModel) — Workspace, Dataset, Report, User, AuditLog | metadata | `models.py`, `migrations/` | FR-090 |
| 1.2 | Alembic migration setup + initial migration | metadata | `alembic.ini`, `migrations/` | — |
| 1.3 | DuckDB store — open/close/list dataset files, version management | storage | `duckdb_store.py` | — |
| 1.4 | Credential encryption (AES-256-GCM encrypt/decrypt) | storage | `credentials.py` | FR-006 |
| 1.5 | Settings validation + startup checks (Postgres reachable, data dir exists) | — | `config.py`, `main.py` | — |
| 1.6 | Tests: metadata CRUD, DuckDB store, credential round-trip | tests | `tests/test_metadata.py`, `tests/test_storage.py` | — |

**Deliverable:** `docker compose up` → API server starts, `/health` returns OK,
PostgreSQL has the schema, `data/datasets/` directory is ready.

---

### Sprint 2: SQL Server Connector (Week 2–3)

**Goal:** Connect to a SQL Server database, browse tables, and import data into DuckDB.

| # | Task | Package | Files | FR |
|---|------|---------|-------|-----|
| 2.1 | SQL Server connector — `test_connection`, `get_tables`, `get_schema`, `read_table` | connectors | `sqlserver.py` | FR-001 |
| 2.2 | Import pipeline — stream from connector → Parquet buffer → DuckDB bulk load | refresh | `importer.py` | — |
| 2.3 | Atomic swap — write new DuckDB file, rename to replace current | refresh | `swap.py` | FR-082 |
| 2.4 | API endpoints: `POST /connections/test`, `GET /connections/{id}/tables`, `GET /connections/{id}/tables/{name}/schema`, `GET /connections/{id}/tables/{name}/preview` | api | `datasets.py` | FR-005, FR-007 |
| 2.5 | API endpoint: `POST /datasets/{id}/refresh` (manual trigger) | api | `refresh.py` | FR-081 |
| 2.6 | Tests: connector against a Docker SQL Server, import pipeline, swap atomicity | tests | `tests/test_connectors.py`, `tests/test_refresh.py` | — |

**Deliverable:** Point MagBI at MSD_ERP → see tables → import a table → data
lives in a `.duckdb` file → query it with raw DuckDB SQL.

---

### Sprint 3: Semantic Model (Week 3–5)

**Goal:** Define tables, relationships, and measures. The model is the contract
between the data and the query engine.

| # | Task | Package | Files | FR |
|---|------|---------|-------|-----|
| 3.1 | Model schema — Pydantic models for DatasetDefinition, TableDef, ColumnDef, RelationshipDef, MeasureDef, RlsRoleDef | model | `schema.py` | FR-020 |
| 3.2 | Relationship manager — add/remove relationships, validate cardinality, find join paths (shortest path in graph) | model | `relationships.py` | FR-021 |
| 3.3 | Date table auto-generation — given a date column, generate Year/Quarter/Month/Week/Day/FiscalYear | model | `date_table.py` | FR-026 |
| 3.4 | Model validation — detect ambiguous paths, circular refs, unused tables, orphan measures | model | `validation.py` | FR-029 |
| 3.5 | API endpoints: CRUD for datasets, relationships, measures | api | `datasets.py` | FR-020, FR-021 |
| 3.6 | Tests: model validation scenarios, date table generation, relationship graph | tests | `tests/test_model.py` | — |

**Deliverable:** Create a dataset from imported tables, define relationships
(e.g., Invoices → Department), add measures (`SUM(Amount)`), validate the model.

---

### Sprint 4: DAX-lite Compiler (Week 5–7)

**Goal:** Parse DAX formulas, resolve references, compile to SQL.

| # | Task | Package | Files | FR |
|---|------|---------|-------|-----|
| 4.1 | Lexer — tokenise DAX-lite source into token stream | dax | `lexer.py` | FR-023 |
| 4.2 | Parser — Pratt parser producing an AST (FunctionCall, BinaryOp, ColumnRef, Literal) | dax | `parser.py` | FR-023 |
| 4.3 | Binder — resolve table/column references against the semantic model, validate types | dax | `binder.py` | FR-023 |
| 4.4 | Compiler — walk AST, emit sqlglot expressions (SUM → sqlglot.exp.Sum, CALCULATE → subquery with filter) | dax | `compiler.py` | FR-023 |
| 4.5 | Built-in functions — SUM, COUNT, AVERAGE, MIN, MAX, DISTINCTCOUNT, DIVIDE, IF, CALCULATE, ALL, FILTER, SAMEPERIODLASTYEAR, DATEADD, TOTALYTD | dax | `functions.py` | FR-023 |
| 4.6 | Tests: lexer round-trip, parser AST shapes, compiler SQL output for each function, edge cases (nested CALCULATE, time intelligence) | tests | `tests/test_dax.py` | — |

**Deliverable:** `SUM(Sales[Amount])` → `SELECT SUM(amount) FROM sales`.
`CALCULATE(SUM(Sales[Amount]), Product[Category]="Electronics")` → correct SQL
with subquery. Time intelligence functions produce correct date-range joins.

---

### Sprint 5: Query Engine (Week 7–9)

**Goal:** The 8-step pipeline: take a semantic query JSON, return a DSR.

| # | Task | Package | Files | FR |
|---|------|---------|-------|-----|
| 5.1 | Semantic query parser — validate SemanticQuery JSON against the model | engine | `pipeline.py` | — |
| 5.2 | Filter context — build the filter tree from query filters + slicer state | engine | `filter_context.py` | — |
| 5.3 | Join resolver — find shortest path between tables in the relationship graph, generate JOIN clauses | engine | `joins.py` | — |
| 5.4 | Chasm-trap detection — detect multi-fact joins through shared dimensions, split into sub-queries + FULL OUTER JOIN | engine | `joins.py` | — |
| 5.5 | SQL generation — assemble SELECT/FROM/JOIN/WHERE/GROUP BY/ORDER BY via sqlglot | engine | `sql_gen.py` | — |
| 5.6 | Query executor — run SQL against DuckDB, return results | engine | `executor.py` | — |
| 5.7 | Post-processing — format numbers, apply sort, shape into DSR | engine | `postprocess.py` | — |
| 5.8 | Query cache — Redis cache keyed by (dataset version + query hash), invalidate on refresh | engine | `cache.py` | — |
| 5.9 | RLS injection — read user attributes from embed token, inject as non-removable WHERE clauses | engine | `filter_context.py` | FR-030, FR-031, FR-032 |
| 5.10 | API endpoint: `POST /query` — accepts SemanticQuery, returns DSR | api | `query.py` | — |
| 5.11 | Tests: pipeline end-to-end with sample DuckDB data, chasm-trap scenarios, RLS enforcement, cache hit/miss | tests | `tests/test_engine.py` | — |

**Deliverable:** Send a semantic query (JSON) → get back formatted data.
This is the **Milestone 1 validation point** — run the 55 existing dashboards'
queries against MagBI's engine.

---

### Sprint 6: Transform Engine (Week 9–10)

**Goal:** Visual transform steps that fold to SQL.

| # | Task | Package | Files | FR |
|---|------|---------|-------|-----|
| 6.1 | Step models — Pydantic models for all 21 step types | transforms | `steps.py` | FR-011, FR-012, FR-013 |
| 6.2 | Folding compiler — walk step list, build sqlglot AST, detect fold boundary | transforms | `folding.py` | FR-015 |
| 6.3 | Python executor — for non-foldable steps (fillDown, partial pivot/unpivot) | transforms | `executor.py` | — |
| 6.4 | Preview endpoint — `POST /transforms/preview` accepts step list, returns 200 rows + fold boundary info | api | `datasets.py` | FR-010 |
| 6.5 | Tests: each step type folds correctly, fold boundary detection, mixed fold/non-fold sequences | tests | `tests/test_transforms.py` | — |

**Deliverable:** User defines transform steps → server compiles to SQL where
possible → returns preview with fold boundary indicator.

---

### Sprint 7: Auth & Embedding (Week 10–11)

**Goal:** JWT auth, workspace roles, embed tokens.

| # | Task | Package | Files | FR |
|---|------|---------|-------|-----|
| 7.1 | JWT token creation and validation (HS256 + RS256) | auth | `tokens.py` | FR-070 |
| 7.2 | Workspace roles — admin/editor/viewer/embed-only permission checks | auth | `roles.py` | FR-090, FR-092 |
| 7.3 | Service token management — create/revoke long-lived tokens | auth | `tokens.py` | FR-093 |
| 7.4 | Embed token endpoint — `POST /embed/token` accepts service token + user attributes, returns scoped embed token | api | `embed.py` | FR-071 |
| 7.5 | Auth middleware — validate JWT on every request, inject user context | auth | `__init__.py` | — |
| 7.6 | Workspace CRUD API | api | `workspaces.py` | FR-090 |
| 7.7 | User management API | api | `admin.py` | FR-092 |
| 7.8 | Tests: token lifecycle, role enforcement, embed token scoping, RLS attribute pass-through | tests | `tests/test_auth.py` | — |

**Deliverable:** ERP sends a service token → gets an embed token → MagBI
validates it and applies RLS. Workspace roles enforce access control.

---

### Sprint 8: Scheduled Refresh (Week 11–12)

**Goal:** Celery worker runs scheduled data refreshes with zero-downtime swap.

| # | Task | Package | Files | FR |
|---|------|---------|-------|-----|
| 8.1 | Refresh orchestrator — Celery task that runs the full import pipeline | refresh | `orchestrator.py` | FR-080 |
| 8.2 | Calculated column computation — after import, evaluate calculated columns | refresh | `calculated.py` | — |
| 8.3 | Concurrent refresh limits — 1 per dataset, 3 per workspace, 10 platform | refresh | `orchestrator.py` | FR-086 |
| 8.4 | Refresh history API — `GET /datasets/{id}/refreshes` with status, duration, errors | api | `refresh.py` | FR-083 |
| 8.5 | Refresh schedule configuration — cron expressions per dataset | metadata | `models.py` | FR-080 |
| 8.6 | Tests: refresh lifecycle, concurrent limit enforcement, failure recovery (old data stays), schedule parsing | tests | `tests/test_refresh_sched.py` | — |

**Deliverable:** Configure "refresh Finance every 30 minutes" → worker runs on
schedule → new DuckDB file swaps in atomically → old data serves during import.

---

### Sprint 9: Report Designer — Frontend (Week 12–14)

**Goal:** Web-based canvas with drag-and-drop visuals and field wells.

| # | Task | Package | Files | FR |
|---|------|---------|-------|-----|
| 9.1 | Canvas component — 1760×990 px, zoom, pan, snap-to-grid (10px) | web/designer | `Canvas.tsx`, `Grid.tsx` | FR-041 |
| 9.2 | Visual palette — sidebar with 13 visual types, drag onto canvas | web/designer | `Palette.tsx` | FR-042 |
| 9.3 | dnd-kit integration — drag visuals on canvas, drag fields into wells | web/designer | `DndContext.tsx` | FR-040 |
| 9.4 | Data pane — tree view of model tables/columns/measures | web/designer | `DataPane.tsx` | FR-043 |
| 9.5 | Field wells — configurable per visual type from registry, auto-aggregation | web/designer | `Wells.tsx` | FR-043, FR-044 |
| 9.6 | Visual rendering — each type maps (data + bindings) → ECharts option | web/visuals | `Bar.tsx`, `Line.tsx`, `Pie.tsx`, `Card.tsx`, `Table.tsx` + 9 more | FR-042 |
| 9.7 | Property pane — colours, labels, titles, conditional formatting | web/designer | `PropertyPane.tsx` | FR-045 |
| 9.8 | Cross-filtering — click emits filter, all visuals re-query | web/designer | `CrossFilter.ts` | FR-046 |
| 9.9 | Filter pane — report/page/visual level filters | web/designer | `FilterPane.tsx` | FR-047 |
| 9.10 | Undo/redo — JSON Patch stack, Ctrl+Z/Y | web/designer | `UndoRedo.ts` | FR-048 |
| 9.11 | Publish button — save report definition, mark as published | web/designer | `PublishButton.tsx` | FR-051 |

**Deliverable:** Open designer → connect to a dataset → drag a bar chart →
drop Revenue on Values and Month on Axis → chart renders live → click a bar →
other visuals filter → publish. This is the **Milestone 2 validation point**.

---

### Sprint 10: Report Viewer & Embed SDK (Week 14–15)

**Goal:** View published reports in a standalone viewer and embedded in iframes.

| # | Task | Package | Files | FR |
|---|------|---------|-------|-----|
| 10.1 | Report viewer component — read-only version of the canvas with full interactivity | web/viewer | `Viewer.tsx` | FR-060 |
| 10.2 | Refresh timestamp display — "Last refreshed: X minutes ago" | web/viewer | `RefreshBadge.tsx` | FR-064 |
| 10.3 | Export to Excel/CSV — download data behind any visual | web/viewer | `Export.tsx` | FR-061 |
| 10.4 | Embed SDK — iframe communication, token injection, theme sync | web/embed | `sdk.ts` | FR-070 |
| 10.5 | Theme injection — host CSS variables → ECharts theme + component styles | web/shared | `theme.ts` | FR-072 |
| 10.6 | Programmatic filter control via SDK | web/embed | `sdk.ts` | FR-073 |
| 10.7 | Token auto-refresh — SDK refreshes embed token before expiry | web/embed | `sdk.ts` | FR-075 |
| 10.8 | Event callbacks — loaded, error, filterChanged, visualClicked | web/embed | `sdk.ts` | FR-074 |

**Deliverable:** Dashboard renders in the ERP's iframe. Theme matches the ERP.
Filters work from both inside the dashboard and from the ERP sidebar.
This is the **Milestone 3 validation point** (with auth from Sprint 7).

---

### Sprint 11: Integration & Migration (Week 15–16)

**Goal:** Migrate all 55 ERP dashboards. Decommission Power BI.

| # | Task | Package | Files | FR |
|---|------|---------|-------|-----|
| 11.1 | Dashboard migration script — read existing Power BI report definitions, generate MagBI report JSON | scripts | `migrate_dashboards.py` | — |
| 11.2 | DAX compatibility audit — verify all DAX functions used in 55 dashboards are covered | scripts | `dax_audit.py` | — |
| 11.3 | ERP dashboard registry integration — update vecfg.BiDashboard entries to point to MagBI URLs | — | ERP-side | IR-004 |
| 11.4 | ERP navigation integration — click handlers from MagBI visuals → ERP pages | web/embed | `sdk.ts` | IR-005 |
| 11.5 | End-to-end testing — each module's dashboards with real data and real RLS | tests | `tests/test_e2e.py` | — |
| 11.6 | Performance profiling — verify < 3s p90 load time on production data | — | — | NFR-001 |

**Deliverable:** All 55 dashboards live in MagBI. Department heads confirm
the dashboards match or exceed Power BI. **Milestone 4 / Phase 1 complete.**

---

## Dependency Graph

```
Sprint 1 (Foundation)
  └─► Sprint 2 (SQL Server Connector)
       └─► Sprint 3 (Semantic Model)
            ├─► Sprint 4 (DAX-lite Compiler)
            │    └─► Sprint 5 (Query Engine) ◄── MILESTONE 1
            └─► Sprint 6 (Transform Engine)
  └─► Sprint 7 (Auth & Embedding) — can start after Sprint 1
  └─► Sprint 8 (Scheduled Refresh) — can start after Sprint 2

Sprint 5 + Sprint 9 (Designer) ◄── MILESTONE 2
Sprint 7 + Sprint 10 (Viewer & SDK) ◄── MILESTONE 3
Sprint 11 (Migration) ◄── MILESTONE 4
```

**Parallelism:** Sprints 7 and 8 can run alongside Sprints 3–5 (they depend on
Sprint 1/2, not on the model or engine). A second developer or AI agent can
tackle them while the primary path works through the query engine.

---

## Getting Started

To begin Sprint 1, use the AI workflow:

```bash
python scripts/ai-feature.py start MAGBI-001 "Foundation: metadata models, DuckDB store, credential encryption"
```

This creates `docs/features/MAGBI-001/README.md` with the analysis/plan template.
Follow the AGENTS.md lifecycle: Analysis → Plan → Execute → Finalize.

---

## Definition of Done (per sprint)

- [ ] All tasks implemented with production code (no stubs)
- [ ] Tests pass with > 80% coverage for the sprint's package
- [ ] `ruff check` and `mypy --strict` pass
- [ ] Knowledge base chapter updated if the implementation differs from the plan
- [ ] Feature branch merged via PR with conventional commit messages
