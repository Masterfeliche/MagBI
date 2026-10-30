# Power BI, taken apart — and our own simple BI engine

How Power BI works inside, layer by layer, and how to build a smaller BI
product of our own that does the same job end to end: connect to data, prepare
it, model it, design reports by drag and drop, publish, share and embed — for
any use case, not only MSD ERP.

| | |
|---|---|
| Written | 29 October 2026 (revised the same day: general BI product, not ERP-only dashboards) |
| Working name | **v2** (rename freely) |
| First customer | MSD ERP: 8 modules, ~55 dashboards to prove it against |
| Recommendation | Python engine (FastAPI + DuckDB + sqlglot) and a React designer. Build a **DAX-lite** formula language, not DAX. MVP in four phases. |

---

## Contents

1. [Power BI in one picture](#1-power-bi-in-one-picture)
2. [Layer by layer](#2-layer-by-layer)
3. [What "a simple Power BI" must do](#3-what-a-simple-power-bi-must-do)
4. [v2 architecture](#4-v2-architecture)
5. [Get data: connectors](#5-get-data-connectors)
6. [Prepare: the transform editor](#6-prepare-the-transform-editor)
7. [Datasets and storage modes](#7-datasets-and-storage-modes)
8. [Model: tables, relationships, hierarchies](#8-model-tables-relationships-hierarchies)
9. [The formula language (DAX-lite)](#9-the-formula-language-dax-lite)
10. [The query engine](#10-the-query-engine)
11. [The report designer](#11-the-report-designer)
12. [Visuals and interaction](#12-visuals-and-interaction)
13. [The service: workspaces, sharing, refresh, embedding](#13-the-service-workspaces-sharing-refresh-embedding)
14. [Metadata store](#14-metadata-store)
15. [Technology choices](#15-technology-choices)
16. [MVP scope and build plan](#16-mvp-scope-and-build-plan)
17. [Risks, and build vs adopt](#17-risks-and-build-vs-adopt)

---

## 1. Power BI in one picture

Power BI is not one program. It is five systems that share a file format:

```
 AUTHORING                     ENGINE                         SERVICE / DELIVERY
┌───────────────────┐   ┌─────────────────────────────┐   ┌──────────────────────────┐
│ Power BI Desktop  │   │ Analysis Services Tabular   │   │ Power BI service         │
│                   │   │ (the "semantic model")      │   │                          │
│  Power Query (M)  │──▶│                             │──▶│  workspaces, apps        │
│  get + shape data │   │  VertiPaq   in-memory       │   │  capacity + scheduler    │
│                   │   │             columnar store  │   │  refresh, caching        │
│  Model view       │   │  Formula engine  (DAX)      │   │  REST + XMLA APIs        │
│  tables, rels,    │   │  Storage engine  (xmSQL)    │   │  embed tokens            │
│  measures (DAX)   │   │  DirectQuery → source SQL   │   │                          │
│                   │   │  RLS / OLS roles            │   └────────────┬─────────────┘
│  Report canvas    │   └──────────────▲──────────────┘                │
│  visuals, theme   │                  │ DAX queries                   │ iframe + token
└────────┬──────────┘                  │                               ▼
         │ PBIX / PBIP        ┌────────┴──────────────────┐   ┌──────────────────────────┐
         │ (TMDL + PBIR)      │ Visual runtime (browser)  │◀──│ Host page                │
         └───────────────────▶│ semantic query → DAX →    │   │ app.powerbi.com or       │
                              │ data-shape result → D3/SVG│   │ powerbi-client in ERP    │
                              └───────────────────────────┘   └──────────────────────────┘
        DATA ACCESS
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ Connectors (M) → on-prem gateway (outbound relay) → SQL Server / files / APIs       │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

The important idea: **the report never touches the database.** Every visual asks
the *semantic model* a question in model terms ("Sum of Amount by Directorate,
filtered to 2026"). The model answers from its own compressed copy (Import) or
by writing SQL against the source (DirectQuery). Everything else — themes,
canvases, embedding — is presentation around that one contract.

---

## 2. Layer by layer

### 2.1 Power Query (the M mashup engine)

- A functional language (M) describing a pipeline of steps: source → filter →
  merge → pivot → change type.
- **Query folding**: the engine pushes as many steps as it can back into the
  source as SQL. Steps that cannot fold are executed row by row inside the
  mashup engine, which is where slow refreshes come from.
- **Privacy levels** stop data from one source leaking into a query sent to
  another; they also disable folding across sources.
- Runs at *refresh* time only — never when a user is looking at a report.
- In the service it runs either in the cloud or, for private sources like
  `192.168.1.3\SQLSERVER2025`, inside the **on-premises gateway**, which opens
  an outbound connection to an Azure relay and never accepts inbound traffic.

### 2.2 VertiPaq — the storage engine

This is the part that makes Power BI fast, and the part worth copying in spirit.

- **Columnar.** Each column is stored separately. A query that needs 3 columns
  of a 60-column table reads 3 columns.
- **Dictionary encoding.** Distinct values go into a dictionary; the column
  stores small integer ids. Cardinality, not row count, drives size.
- **Value encoding** for numbers (store `value − min`, with fewer bits).
- **Run-length encoding** after sorting rows to maximise runs.
- **Segments** of ~1M rows (8M with large-model format), scanned in parallel
  across cores, with min/max metadata to skip whole segments.
- **Relationships** are pre-built indexes from a fact row to a dimension row,
  so a join at query time is a lookup, not a hash join.
- Calculated columns are materialised at refresh; measures are not stored at all.

### 2.3 The formula engine and DAX

DAX is a query language over the model. Every query is split in two:

| | Storage engine (SE) | Formula engine (FE) |
|---|---|---|
| Threads | Many | One per query |
| Does | Scans, simple filters, `SUM/COUNT/MIN/MAX/DISTINCTCOUNT`, joins along relationships | Everything else: iterators, branching, context transition, time intelligence |
| Speaks | xmSQL (internal) | DAX query plan |
| Caches | Yes (SE cache) | No |

A fast DAX measure is one the FE can turn into a few big SE scans. A slow one
forces the FE to call back into the SE row by row (`CallbackDataID`).

The semantics that make DAX hard — and that v2 must decide on deliberately:

1. **Filter context.** Every visual cell is evaluated under the filters coming
   from its row/column headers, slicers, page and report filters.
2. **Filter propagation.** Filters flow from the one side of a relationship to
   the many side (dimension → fact). Bi-directional is opt-in.
3. **`CALCULATE`** rewrites the filter context — `CALCULATE([Sales], Year = 2025)`
   replaces the Year filter. This is how "previous year", "% of total" and
   "all directorates" are written.
4. **Context transition.** Inside an iterator, the current row becomes a filter.
5. **Auto-exist / `SUMMARIZECOLUMNS`.** Only combinations of grouping columns
   that actually exist are returned, and blank rows are dropped. Visuals rely on
   this to avoid a cartesian product.
6. **Blank** is not zero and not null; arithmetic and comparisons treat it specially.

### 2.4 Storage modes

| Mode | Data lives in | Query goes to | Freshness | Notes |
|---|---|---|---|---|
| Import | VertiPaq copy | Memory | As of last refresh | What MSD ERP uses today |
| DirectQuery | Source | Generated SQL on the source | Live | Every visual = SQL on production ERP |
| Dual | Both | Whichever fits | Mixed | For shared dimensions in composite models |
| Composite | Mix per table | Mix | Mixed | Aggregation tables in Import over DQ detail |
| Direct Lake | Delta/Parquet in OneLake | Pages columns into VertiPaq on demand | Near-live | Fabric only |

### 2.5 The report and visual layer

- A report (PBIR in PBIP format — the JSON `bi_lib.py` generates) is a list of
  pages, each a list of visuals with position, size, field bindings, formatting
  and filters. **It contains no data and no SQL.**
- In the browser each visual builds a **semantic query** (fields + filters in
  model terms), which the service translates to a DAX query, usually
  `SUMMARIZECOLUMNS(...)`.
- The answer comes back as a compressed **data-shape result** (DSR), already
  limited by **data reduction** (e.g. top 1,000 categories, 3,500 points on a
  line, sampling on scatter).
- Visuals render with SVG/D3 (or canvas for heavy ones). Custom visuals run in a
  sandboxed iframe.
- **Cross-filter / cross-highlight**: clicking a bar adds a filter to every
  other visual's semantic query, and each re-queries. Highlight sends two
  queries — the total and the filtered part.
- The **theme** JSON sets palette, fonts and default formatting; anything set on
  a visual overrides it.

### 2.6 The service

- **Workspaces** hold semantic models, reports, dashboards (tiles pinned from
  reports) and apps (a packaged audience view).
- **Capacity** is the compute. Shared capacity (Pro) is multi-tenant with tight
  limits — including the monthly allowance of embed tokens that the PoC runbook
  warns about. Fabric F-SKUs are dedicated, metered in capacity units, with
  smoothing of background work (refresh) over 24 hours.
- Models are **evicted** from memory when idle and reloaded on first query —
  the "first open is slow" effect.
- **Query result cache** and **tile cache** sit in front of the engine.
- **Scheduled refresh** runs Power Query, rebuilds VertiPaq, then swaps the new
  copy in atomically.
- **APIs**: REST (workspaces, reports, refresh, `GenerateToken`) and XMLA (the
  Analysis Services protocol, for TMDL/tabular tooling) on Premium/Fabric.

### 2.7 Embedding and security

- *User owns data*: the viewer signs in to Microsoft; their licence applies.
- *App owns data* (what the PoC does): a service principal calls `GenerateToken`
  for one report + model; the browser loads `app.powerbi.com/reportEmbed` in an
  iframe via `powerbi-client` with that token.
- **RLS** is a DAX filter per role (e.g. `[Directorate] = USERPRINCIPALNAME()`
  via a mapping table). For app-owns-data it only applies if the token request
  passes an `effectiveIdentity` with a username and roles. **The PoC's tokens
  carry no identity, so today there is no row-level filtering — access is
  per-dashboard only**, decided in the ERP/PoC before the token is minted.

---

## 3. What "a simple Power BI" must do

A user (an analyst, not a developer) has to be able to go through the same six
steps as in Power BI Desktop + service, entirely in the browser:

```
 1 GET DATA      2 PREPARE         3 MODEL             4 VISUALISE          5 PUBLISH        6 CONSUME
┌───────────┐   ┌─────────────┐   ┌───────────────┐   ┌────────────────┐   ┌────────────┐   ┌──────────────┐
│ pick a    │──▶│ filter,     │──▶│ relationships │──▶│ drag fields    │──▶│ to a       │──▶│ view, filter │
│ source,   │   │ rename,     │   │ hierarchies   │   │ onto visuals,  │   │ workspace; │   │ cross-filter │
│ tables or │   │ join, group │   │ measures      │   │ format, pages, │   │ schedule   │   │ export, embed│
│ a file    │   │ add columns │   │ (DAX-lite)    │   │ slicers, theme │   │ refresh    │   │ in ERP / apps│
└───────────┘   └─────────────┘   └───────────────┘   └────────────────┘   └────────────┘   └──────────────┘
   connectors     recipe → SQL       semantic model      report JSON         service          viewer + SDK
```

| Power BI piece | v2 equivalent | In MVP? |
|---|---|---|
| Get Data (100+ connectors) | SQL Server, PostgreSQL, MySQL, CSV, Excel | Yes (5) |
| Power Query (M) | Step-based **transform recipe**, compiled to SQL | Yes, ~12 step types |
| VertiPaq / Import | **DuckDB** file per dataset | Yes |
| DirectQuery | Push SQL to the source via **sqlglot** dialect transpile | Phase 4 |
| Model view | Diagram editor: tables, relationships, hierarchies, date table | Yes |
| DAX | **DAX-lite**: measures, calculated columns, ~40 functions | Yes |
| Report canvas | Drag-and-drop designer, multi-page, fields/format/filter panes | Yes |
| Visuals | ~12 core visuals on ECharts | Yes |
| Cross-filter, slicers, drill | Yes; drill-down on hierarchies, drill-through | Cross-filter yes, drill phase 3 |
| Themes | JSON theme → CSS tokens (MSD "ERP Native" ships as one) | Yes |
| Workspaces, roles, sharing | Workspaces with Admin / Member / Contributor / Viewer | Yes |
| RLS | Roles with DAX-lite filter, mapped to users | Phase 3 |
| Scheduled refresh | Built-in scheduler; no gateway needed on the LAN | Yes |
| Embed (embed token) | Signed short-lived token + JS SDK, rendered in the host page | Phase 3 |
| Export | CSV/Excel of a visual; PDF of a page | Phase 3 |
| Paginated, Q&A, Copilot, dataflows, mobile apps | — | No |

---

## 4. v2 architecture

```
 BROWSER  (React + TypeScript)
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Data hub │ Prep editor │ Model editor │ Report designer │ Viewer │ Admin         │
│ ─────────────────────────────── shared ────────────────────────────────────────  │
│ visual library (ECharts) · filter/selection state · theme tokens · API client    │
└──────────────────────────────┬───────────────────────────────────────────────────┘
                               │ REST/JSON  (/api/...)          ▲ embed SDK
                               ▼                                │ (ERP, other apps)
 SERVER  (Python · FastAPI)                                      │
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Auth & permissions  ── users, workspaces, roles, RLS, embed tokens               │
│                                                                                  │
│ Catalog API         ── connections, datasets, models, reports, versions          │
│                                                                                  │
│ ENGINE                                                                           │
│  connectors ─▶ prep compiler ─▶ loader ─▶ DuckDB dataset files  (Import)         │
│                                                                                  │
│  formula parser ─▶ model binder ─▶ query planner ─▶ SQL generator ─▶ executor    │
│      (DAX-lite)      (names, rels)   (filter ctx)     (sqlglot)     DuckDB or    │
│                                                                     source (DQ)  │
│  result cache (model ver + query + RLS)                                          │
│                                                                                  │
│ Scheduler           ── refresh jobs, retries, history                            │
└────────┬───────────────────────────────┬────────────────────────────┬────────────┘
         ▼                               ▼                            ▼
  Metadata DB                     data/ datasets/*.duckdb       Sources: SQL Server,
  (SQL Server or Postgres;        one file per dataset          Postgres, MySQL, files
   SQLite in dev)                 versioned, atomic swap
```

Three contracts hold the whole thing together, and every component speaks only
in them:

1. **Dataset definition** (JSON): sources, recipes, tables, relationships,
   measures, roles. The equivalent of TMDL.
2. **Semantic query** (JSON): `{dataset, groupBy, measures, filters, sort,
   limit}`. What a visual asks. The equivalent of Power BI's semantic query.
3. **Report definition** (JSON): pages, visuals, field bindings, formatting,
   filters, theme. The equivalent of PBIR. Contains no data and no SQL.

---

## 5. Get data: connectors

```python
class Connector(Protocol):
    kind: str                                   # "sqlserver", "postgres", "csv", ...
    dialect: str                                # sqlglot dialect name, e.g. "tsql"
    def test(self) -> None: ...
    def list_schemas(self) -> list[Schema]: ...
    def list_tables(self, schema: str) -> list[TableInfo]: ...
    def preview(self, sql: str, limit: int = 200) -> pa.Table: ...
    def read(self, sql: str) -> Iterator[pa.RecordBatch]: ...   # streamed, for import
```

- **Database connectors** (SQL Server via `pyodbc`/`mssql-python`, Postgres,
  MySQL) take credentials that are stored **encrypted** in the metadata DB
  (Fernet/AES key from the environment, never in the DB) and never returned to
  the browser.
- **File connectors** (CSV, Excel, Parquet): upload → stored under
  `data/uploads/` → DuckDB reads them natively (`read_csv_auto`, Excel via
  `openpyxl`/`calamine`).
- The data hub shows a **schema browser** and a 200-row preview, like the
  Navigator dialog in Power BI.
- Every connection is tagged with an owner workspace; using it needs Member or above.

---

## 6. Prepare: the transform editor

Power Query's idea — an ordered list of applied steps, each previewable — without
the M language. A table's recipe is JSON:

```json
{
  "source": { "connection": "msd-erp", "table": "vetsp.Trip" },
  "steps": [
    { "op": "select",  "columns": ["TripGuid", "VehicleGuid", "StartDate", "DistanceKm", "Status"] },
    { "op": "filter",  "where": "Status <> 'Cancelled'" },
    { "op": "rename",  "map": { "DistanceKm": "Distance (km)" } },
    { "op": "type",    "column": "StartDate", "to": "date" },
    { "op": "add_column", "name": "Long trip", "expr": "IF([Distance (km)] > 300, \"Yes\", \"No\")" },
    { "op": "join",    "with": "Vehicle", "on": [["VehicleGuid", "VehicleGuid"]], "kind": "left",
                       "columns": ["VehicleType"] }
  ]
}
```

Step types for the MVP: `select`, `rename`, `filter`, `type`, `add_column`
(row-level DAX-lite expression), `replace_values`, `remove_duplicates`, `sort`,
`join`, `append`, `group_by`, `unpivot`, `fill_down`.

**Query folding, done simply.** The prep compiler turns the recipe into one
SQL statement with `sqlglot`:

1. Build the statement step by step as a sqlglot expression tree (each step
   wraps the previous as a subquery; sqlglot's optimiser flattens them).
2. If every step is supported by the source dialect, transpile to that dialect
   (`tsql`, `postgres`, `mysql`) and run it **at the source** — that is folding.
3. Otherwise pull the folded prefix from the source and run the rest in DuckDB.
4. The editor shows a "folds to source" badge per step, as Power BI shows "View
   Native Query".

Every step is previewed by running the recipe up to that step with `LIMIT 200`.

---

## 7. Datasets and storage modes

A **dataset** = connections + table recipes + model + measures + roles. It is
the unit that is refreshed, versioned, secured and that reports bind to —
exactly like a Power BI semantic model, and many reports can share one.

| Mode | How | When |
|---|---|---|
| **Import** (default) | Refresh runs each recipe, streams Arrow batches into `data/datasets/<id>/<version>.duckdb`, validates, then atomically swaps the "current" pointer | Almost always: fast, isolates the source from report load |
| **DirectQuery** (phase 4) | Planner generates SQL, sqlglot transpiles it to the source dialect, executes at the source | Data too large or must be live |
| **Hybrid** (later) | Import aggregates, DirectQuery detail | Very large facts |

Refresh validations: row counts, key uniqueness on the one side of every
relationship, orphan-key ratio, and a schema drift check. A failed refresh keeps
serving the previous version and records why. Incremental refresh (by a
modified-date column) comes in phase 4.

Why DuckDB: it is the closest open equivalent to VertiPaq — columnar,
compressed, vectorised, parallel, in-process (no server to run) — and it reads
Parquet/CSV/Excel directly. A dataset of tens of millions of rows answers
typical visual queries in milliseconds on one machine.

---

## 8. Model: tables, relationships, hierarchies

The model editor is a **diagram view** (React Flow): tables as boxes,
relationships as lines you drag from column to column.

```json
{
  "tables": [
    { "name": "Trip",    "columns": [ { "name": "Distance (km)", "type": "decimal",
                                        "format": "#,0", "summarize": "sum" } ] },
    { "name": "Vehicle", "columns": [ { "name": "VehicleType", "type": "string" } ] },
    { "name": "Date",    "isDateTable": true, "dateColumn": "Date",
      "hierarchies": [ { "name": "Calendar", "levels": ["Year", "Quarter", "Month", "Date"] } ] }
  ],
  "relationships": [
    { "from": "Trip.VehicleGuid", "to": "Vehicle.VehicleGuid",
      "cardinality": "many-to-one", "crossFilter": "single", "active": true },
    { "from": "Trip.StartDate", "to": "Date.Date",
      "cardinality": "many-to-one", "crossFilter": "single", "active": true }
  ]
}
```

- **Cardinality**: many-to-one and one-to-one in MVP. Many-to-many via a bridge
  table later.
- **Cross-filter direction**: single (dimension → fact) by default; "both" is
  allowed per relationship and compiled as a semi-join.
- **Inactive relationships** can be stored and activated in a measure with
  `USERELATIONSHIP` (phase 3).
- **Auto-detect** relationships on matching column names and key uniqueness,
  as Power BI does — the user confirms.
- **Date table**: "Mark as date table", or let v2 generate one
  (`Date, Year, Quarter, Month, MonthName, Week, Day, FiscalYear…`).
- **Default summarisation** per numeric column, so dragging a column onto a
  visual sums it without a measure — an "implicit measure", as in Power BI.
- Column properties: display name, format, data category (country, URL, image),
  sort-by column (MonthName sorted by Month), hidden.

---

## 9. The formula language (DAX-lite)

The single biggest design decision. Users expect to write formulas like DAX; we
cannot implement all of DAX. So: **DAX syntax, a deliberately smaller set of
functions, and semantics that compile to SQL.**

### 9.1 What can be written

```
Total Distance      = SUM(Trip[Distance (km)])
Trips               = COUNTROWS(Trip)
Avg Trip            = DIVIDE([Total Distance], [Trips])
Completed Trips     = CALCULATE([Trips], Trip[Status] = "Completed")
Completion %        = DIVIDE([Completed Trips], [Trips])
Trips LY            = CALCULATE([Trips], SAMEPERIODLASTYEAR('Date'[Date]))
Trips YTD           = TOTALYTD([Trips], 'Date'[Date])
Share of Trips      = DIVIDE([Trips], CALCULATE([Trips], ALL(Vehicle[VehicleType])))
Fuel Cost           = SUMX(Trip, Trip[Fuel L] * RELATED(Vehicle[Fuel Price]))
Status              = SWITCH(TRUE(), [Completion %] >= 0.95, "Good",
                                     [Completion %] >= 0.8,  "Watch", "Poor")
```

Calculated column (row context, stored at refresh):
```
Trip[Long trip]     = IF(Trip[Distance (km)] > 300, "Yes", "No")
```

### 9.2 Function set for the MVP (~40)

| Group | Functions |
|---|---|
| Aggregation | `SUM AVERAGE MIN MAX COUNT COUNTA COUNTROWS DISTINCTCOUNT MEDIAN` |
| Iterators | `SUMX AVERAGEX MINX MAXX COUNTX` (single table + `RELATED`) |
| Filter | `CALCULATE FILTER ALL ALLEXCEPT REMOVEFILTERS KEEPFILTERS VALUES SELECTEDVALUE HASONEVALUE ISFILTERED` |
| Time intelligence | `TOTALYTD TOTALQTD TOTALMTD DATESYTD SAMEPERIODLASTYEAR DATEADD PREVIOUSMONTH PREVIOUSYEAR PARALLELPERIOD` |
| Logic | `IF SWITCH AND OR NOT IFERROR ISBLANK BLANK COALESCE` |
| Math | `DIVIDE ROUND ABS INT MOD POWER` |
| Text | `CONCATENATE LEFT RIGHT MID UPPER LOWER LEN FORMAT` |
| Date | `YEAR MONTH DAY TODAY DATE DATEDIFF EOMONTH WEEKDAY` |
| Relationship | `RELATED USERELATIONSHIP` (phase 3) |
| Variables | `VAR … RETURN` |

Not in scope: table-returning measures that build arbitrary virtual tables
(`ADDCOLUMNS/SUMMARIZE/GENERATE/TOPN` inside measures), `EARLIER`,
calculation groups, recursion. The editor says so with a clear error, with the
position of the unsupported function.

### 9.3 Pipeline

```
text ─▶ lexer ─▶ parser (Pratt, ~600 lines) ─▶ AST ─▶ binder ─▶ type checker ─▶ IR
                                                     (tables, columns,   (scalar vs
                                                      measures, cycles)   table, row vs
                                                                          filter context)
```

The editor gets IntelliSense-style completion from the binder (table, column,
measure and function names), and errors with line/column.

### 9.4 Semantics — how a measure becomes SQL

A visual cell is evaluated under a **filter context**: a set of predicates per
column, coming from the visual's group-by values, slicers, page/report filters
and RLS. The compiler represents it as `FilterContext = {column → predicate}`.

| DAX-lite construct | Effect on filter context | SQL shape |
|---|---|---|
| Aggregation `SUM(T[c])` | Evaluated under the current context | `SUM(c)` in a sub-query over T joined to filtered dimensions |
| `CALCULATE(e, T[c] = v)` | **Replaces** filters on `T[c]` with `= v` | separate aggregate with its own `WHERE`, or `SUM(c) FILTER (WHERE …)` if only the fact is touched |
| `KEEPFILTERS(...)` | **Intersects** instead of replacing | `AND` with existing predicate |
| `ALL(T[c])` / `REMOVEFILTERS` | Removes filters on that column (or whole table) | aggregate grouped without that column, joined back |
| `ALLEXCEPT(T, T[c])` | Removes all but `c` | same, keeping `c` |
| Time intelligence | Rewrites the predicate on the marked date column (shift, to-date range) | date-range predicate computed per output row via the date table |
| `SUMX(T, expr)` | Row context over T | `SUM(expr)` when `expr` uses only T and `RELATED` columns |
| Measure reference `[m]` | Inline m's expression in the current context (context transition is implicit) | composed in the outer `SELECT` |
| `DIVIDE(a, b)` | — | `a / NULLIF(b, 0)` |
| `BLANK()` | SQL `NULL` | rows where every measure is `NULL` are dropped (auto-exist) |

Each distinct **(aggregation, filter context)** pair becomes one aggregate
sub-query at the visual's grain. The planner merges pairs that share a context
into one scan (the equivalent of Power BI's storage-engine fusion). That one rule
explains most of the engine.

### 9.5 Totals

Totals and subtotals are **re-evaluated at the coarser grain**, not summed from
the rows — so ratios, distinct counts and averages total correctly, as in Power
BI. Simple additive measures use `GROUPING SETS` in one query; anything else
runs once per total level.

---

## 10. The query engine

### 10.1 The semantic query

```json
{
  "dataset": "ds_transport",
  "groupBy": ["Vehicle[VehicleType]", "Date[Month]"],
  "measures": ["[Trips]", "[Completion %]", "[Trips LY]"],
  "filters": [
    { "column": "Date[Year]", "op": "in", "values": [2026] },
    { "column": "Vehicle[VehicleType]", "op": "notIn", "values": ["Motorcycle"] }
  ],
  "orderBy": [{ "expr": "[Trips]", "dir": "desc" }],
  "limit": 1000,
  "totals": true
}
```

Implicit measures (a column dropped on Values) arrive as
`{"column": "Trip[Distance (km)]", "agg": "sum"}`.

### 10.2 Planning steps

1. **Bind** names against the model; unknown → 400. The browser never sends SQL.
2. **Build the base filter context** from `filters` + RLS predicates for the caller.
3. **Compile measures** to IR; collect `(aggregation, context, home table)` leaves.
4. **Resolve join paths** from each leaf's home table to every group-by and
   filter column, walking relationships in their filter direction. No path →
   the measure is not filtered by that column (as in Power BI), and the UI shows
   a warning icon on the visual.
5. **Group leaves by (home table, context)** → one sub-query each:
   `SELECT groupBy…, agg1, agg2 FROM fact JOIN dims WHERE ctx GROUP BY groupBy…`.
6. **Combine** sub-queries with `FULL OUTER JOIN` on the group-by columns
   (avoids the fan-out/chasm trap of joining two facts directly).
7. **Compute** scalar expressions (`DIVIDE`, `IF`, `SWITCH`, arithmetic) in the outer `SELECT`.
8. **Drop all-blank rows**, sort, apply **data reduction** (top N categories,
   max points for lines), and compute totals (9.5).
9. Generate SQL with **sqlglot** in the target dialect (`duckdb` for Import,
   source dialect for DirectQuery), execute, return Arrow → JSON.

### 10.3 Response

```json
{
  "columns": [
    { "name": "Vehicle[VehicleType]", "type": "string" },
    { "name": "[Trips]", "type": "integer", "format": "#,0" }
  ],
  "rows": [["Truck", "2026-01", 412, 0.93, 380]],
  "totals": [null, null, 1830, 0.91, 1702],
  "reduced": false,
  "asOf": "2026-10-29T08:00:00+03:00",
  "durationMs": 14
}
```

### 10.4 Caching and performance

- Result cache key: `dataset version + normalised query + RLS context`.
  Invalidated automatically by a refresh, which bumps the version.
- Visuals on a page query **in parallel**; one DuckDB connection per worker,
  datasets opened read-only.
- A **Performance analyzer** panel in the designer shows each visual's
  semantic query, generated SQL and timing — the Power BI feature that will
  save us the most debugging time.

---

## 11. The report designer

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│ File  Home  Insert  Format  View          [ Save ] [ Publish ] [ Preview ]         │
├──────────┬───────────────────────────────────────────────────────┬─────────────────┤
│ Filters  │                                                       │ Visualizations  │
│ ───────  │   ┌──────────┐ ┌──────────┐ ┌──────────┐              │ ▢ ▤ ▥ ◔ ⌇ ▦ ⊞   │
│ This     │   │ KPI card │ │ KPI card │ │ KPI card │              │ ───────────────  │
│ visual   │   └──────────┘ └──────────┘ └──────────┘              │ X-axis  [Month] │
│ This     │   ┌────────────────────────┐ ┌──────────────┐         │ Y-axis  [Trips] │
│ page     │   │  column chart          │ │  donut       │         │ Legend  [Type]  │
│ All      │   │                        │ │              │         │ Tooltip         │
│ pages    │   └────────────────────────┘ └──────────────┘         │ ─── Format ───  │
│          │   ┌───────────────────────────────────────┐           │ Title, colours, │
│          │   │  table                                │           │ labels, axes    │
│          │   └───────────────────────────────────────┘           │ ─── Data ───    │
│          │                                                       │ ▸ Trip          │
│          │  [ Page 1 ] [ Page 2 ] [ + ]                          │ ▸ Vehicle       │
│          │                                                       │ ▸ Date          │
└──────────┴───────────────────────────────────────────────────────┴─────────────────┘
```

- **Canvas**: fixed page size (16:9 default, custom like 1760×990) with
  absolute positioning, snap to grid, align/distribute, z-order, copy/paste,
  undo/redo (command stack over the report JSON). `react-rnd` or a small own
  drag layer; `dnd-kit` for dragging fields into wells.
- **Fields pane**: tables, columns, measures, hierarchies from the dataset.
  Drag onto the canvas creates a sensible default visual (as Power BI does).
- **Wells** per visual type (Axis, Values, Legend, Tooltips, Rows, Columns…),
  each declaring accepted kinds (category, numeric, date, measure) and max fields.
- **Format pane** generated from each visual's **format schema** (JSON schema
  per visual type), so adding a visual does not mean writing new pane UI.
- **Filters pane**: visual / page / report level; basic (list), advanced
  (conditions), top N, relative date.
- **Theme**: report-level JSON (palette, fonts, visual defaults), importable,
  with the MSD theme as a built-in.
- **Measures in the report**: "New measure" opens the formula editor (Monaco
  with DAX-lite syntax highlighting and completion) and saves to the dataset.
- Autosave drafts; **Publish** creates an immutable report version.

Report definition, abbreviated:

```json
{
  "id": "rpt_fleet", "dataset": "ds_transport", "theme": "erp-native",
  "pages": [{
    "id": "p1", "name": "Overview", "size": [1760, 990],
    "filters": [{ "column": "Date[Year]", "type": "basic", "values": [2026] }],
    "visuals": [{
      "id": "v1", "type": "columnChart", "pos": { "x": 24, "y": 140, "w": 820, "h": 380, "z": 2 },
      "wells": { "category": ["Date[Month]"], "values": ["[Trips]", "[Trips LY]"],
                 "legend": [] },
      "format": { "title": { "text": "Trips by month" }, "dataLabels": { "show": false } },
      "filters": [], "interactions": { "v4": "filter" }
    }]
  }]
}
```

---

## 12. Visuals and interaction

### 12.1 Visual plug-in contract

```ts
interface VisualDefinition {
  type: string;                              // "columnChart"
  wells: WellSpec[];                         // what can be dropped where
  formatSchema: JSONSchema;                  // drives the Format pane
  toQuery(wells, ctx): SemanticQuery[];      // usually one query
  render(el: HTMLElement, data, format, theme, events): VisualHandle;
}
```

New visuals are added by registering a definition — the equivalent of custom
visuals, without the marketplace.

MVP visuals: **card, multi-row card / KPI, table, matrix, bar, column
(clustered / stacked / 100%), line, area, combo (line + column), pie, donut,
slicer (list, dropdown, date range)**. Phase 3: scatter, map (Leaflet), gauge,
waterfall, funnel, treemap, text box, image, shape, button.

### 12.2 Interaction model

- One **selection state** per page: slicer values + selected data points.
- Each visual's query = its wells + page/report filters + slicers + other
  visuals' selections (never its own).
- Edit interactions per pair of visuals: filter / none (highlight in phase 3).
- **Drill down** on hierarchies (Year → Quarter → Month) — the visual keeps a
  drill path and re-queries one level deeper with the parent as a filter.
- **Drill-through**: a page declares drill-through fields; right-click a data
  point → navigate with those values as filters.
- **Tooltips**: default field tooltips; report-page tooltips in phase 4.
- Queries are debounced and cancellable — a new click aborts stale requests.

---

## 13. The service: workspaces, sharing, refresh, embedding

| Concept | v2 |
|---|---|
| Workspace | Container of connections, datasets and reports |
| Workspace roles | Admin (manage members), Member (publish, share), Contributor (create/edit), Viewer (view) |
| Sharing | Share a report with users/groups as Viewer; or an **App** = curated list of reports for an audience |
| Dataset permissions | Build permission: lets others create reports on a shared dataset |
| RLS | Roles on the dataset: `{name, table, filter: "Vehicle[Region] = USERATTR(\"region\")"}`; members are users/groups; predicates are injected into every query (§10.2 step 2) and tested with "View as role" in the designer |
| Refresh | Cron schedule per dataset, on-demand button, retries, history with duration/rows/errors, e-mail on failure |
| Embedding | Server-to-server: host app calls `POST /api/embed/token` with its API key, report id and the end user's identity/attributes → short-lived signed JWT. Host page loads `v2-embed.js` and renders the report **into its own DOM** (no iframe needed, iframe optional) |
| Audit | Who viewed, exported, edited, refreshed what |
| Auth | Local accounts first; OIDC (Entra ID, Google, Keycloak) in phase 3 |

For MSD ERP this means: no Microsoft tenant, no gateway, no capacity, no embed
quota, and ERP users carried into RLS by the embed token.

---

## 14. Metadata store

Relational, small, accessed through SQLAlchemy so it runs on SQLite in dev and
SQL Server or Postgres in production. Definitions are stored as JSON documents,
with versions.

```
users(id, email, name, password_hash, is_active, created_at)
groups(id, name)                         group_members(group_id, user_id)
workspaces(id, name, description)        workspace_members(workspace_id, principal, role)
connections(id, workspace_id, kind, name, config_json, secret_encrypted)
datasets(id, workspace_id, name, current_version, mode, schedule_cron)
dataset_versions(dataset_id, version, definition_json, created_by, created_at)
dataset_refreshes(id, dataset_id, version, status, started_at, finished_at, rows_json, error)
rls_roles(id, dataset_id, name, filter_expr)   rls_members(role_id, principal)
reports(id, workspace_id, dataset_id, name, current_version)
report_versions(report_id, version, definition_json, published, created_by, created_at)
apps(id, workspace_id, name)             app_items(app_id, report_id, order)   app_audience(app_id, principal)
embed_clients(id, name, api_key_hash, allowed_origins, workspace_id)
audit_log(id, at, principal, action, object_type, object_id, detail_json)
```

---

## 15. Technology choices

| Layer | Choice | Why |
|---|---|---|
| Engine + API | **Python 3.12, FastAPI, Pydantic** | Best ecosystem for this exact job; the team already writes Python (`bi_lib.py`, audit scripts) |
| Analytic store | **DuckDB** | VertiPaq-class columnar engine, in-process, free |
| SQL generation | **sqlglot** | Builds SQL as a tree; transpiles to T-SQL, Postgres, MySQL, DuckDB — gives us folding and DirectQuery almost for free |
| Data interchange | **Apache Arrow** (`pyarrow`) | Zero-copy from connectors into DuckDB and out to JSON |
| Connectors | `mssql-python`/`pyodbc`, `psycopg`, `pymysql`, DuckDB file readers | |
| Scheduler | APScheduler (in-process) → Celery/RQ if it needs to scale | |
| Metadata | SQLAlchemy + Alembic; SQLite (dev), SQL Server/Postgres (prod) | |
| Front end | **React + TypeScript + Vite** | |
| Charts | **Apache ECharts** | All MVP visuals, canvas rendering, large data, theming |
| Designer | `dnd-kit`, `react-rnd`, React Flow (model diagram), Monaco (formula editor), Zustand (state) | |
| Tables | TanStack Table (virtualised) for table/matrix | |
| Packaging | One Docker image (API + static web); runs on a Windows server too | |

**Alternative: .NET.** Possible (ASP.NET + DuckDB.NET), and closer to the PoC
app, but there is no sqlglot equivalent in .NET — we would write SQL
generation and dialect handling ourselves. The PoC's sign-in and catalog code
can still front v2 in the ERP through the embed API.

### Repository layout

```
v2/
  engine/                     # pure Python package, no web code
    connectors/               sqlserver.py, postgres.py, mysql.py, files.py
    prep/                     recipe model, step compilers, folding
    model/                    dataset definition, validation, relationship graph, date table
    formula/                  lexer.py, parser.py, ast.py, binder.py, functions/, ir.py
    query/                    semantic_query.py, planner.py, sqlgen.py, totals.py, reduction.py
    storage/                  duckdb_store.py (versions, atomic swap), refresh.py
    security/                 rls.py
    cache.py
  server/                     # FastAPI app
    api/                      connections, datasets, models, query, reports, workspaces, embed, admin
    auth/  scheduler/  db/ (SQLAlchemy models, Alembic migrations)
  web/                        # React app
    src/data-hub/ prep-editor/ model-editor/ designer/ viewer/ admin/
    src/visuals/              one folder per visual: definition.ts, render.ts, format.schema.json
    src/embed/                v2-embed.js SDK
  tests/
    formula/                  parser + compile golden tests
    query/                    SQL snapshot tests, result tests on fixture data
    parity/                   numbers vs Power BI for MSD dashboards
  samples/                    a demo dataset (CSV) + report, so the app is useful on first run
```

---

## 16. MVP scope and build plan

Estimates assume **2–3 developers**. Each phase ends with something a person can
use, and with MSD dashboards as the acceptance test.

### Phase 1 — engine core (5–6 weeks)
- Dataset definition, model validation, relationship graph, date table.
- Connectors: SQL Server, CSV, Excel. Import into DuckDB with versions + atomic swap.
- DAX-lite: lexer, parser, binder; aggregations, `CALCULATE` with column
  filters, `ALL/REMOVEFILTERS`, `DIVIDE`, `IF/SWITCH`, `VAR`, measure references.
- Query planner + SQL generation (sqlglot → DuckDB), totals, blank-row removal.
- `/api/query` endpoint; CLI to load a dataset JSON and run a query.
- **Exit:** the Transport model rebuilt as a dataset; every number of Fleet
  Availability reproduced through `/api/query`, compared with Power BI.

### Phase 2 — designer and viewer (6–8 weeks)
- Data hub (connections, schema browser, preview), model diagram editor,
  formula editor with completion.
- Report designer: canvas, fields/wells, format pane from schemas, filters
  pane, pages, themes, undo/redo, save/publish.
- Visuals: card, KPI, table, matrix, bar/column, line/area, combo, pie/donut, slicers.
- Cross-filtering. Viewer with fit-to-page.
- **Exit:** an analyst builds Fleet Availability from scratch in the browser
  without touching JSON.

### Phase 3 — service (5–6 weeks)
- Workspaces, roles, sharing, apps; RLS with "View as"; scheduled refresh +
  history; embed tokens + SDK; export CSV/Excel; audit log; OIDC sign-in.
- Prep editor (transform steps with folding badges).
- Time intelligence functions, `SUMX` family, drill-down/drill-through, more visuals.
- **Exit:** one MSD module (Transport, 9 dashboards) live in the ERP via the
  embed SDK, running side by side with Power BI.

### Phase 4 — breadth (ongoing)
- DirectQuery, incremental refresh, Postgres/MySQL, PDF export, e-mail
  subscriptions, alerts, maps, report-page tooltips, cross-highlight, mobile layout.
- Migrate remaining MSD modules; retire the Power BI workspace, gateway and embed code.

**Realistic total to a usable v1:** about 4–5 months for phases 1–3 with 2–3
people. A single developer: roughly double.

---

## 17. Risks, and build vs adopt

| Risk | Mitigation |
|---|---|
| DAX-lite semantics differ from what users expect (totals, blanks, filter replacement) | Golden tests for every function on a fixture dataset; document each difference from DAX in the editor's help; parity tests against Power BI |
| Users write DAX we don't support | Parser recognises full DAX function names and reports "not supported in v2" with the location, not a generic syntax error |
| Designer UX is a bottomless pit | Copy Power BI's layout and conventions exactly — users already know them; resist novel UI |
| Performance on big data | DuckDB scales to hundreds of millions of rows on one box; add aggregation tables and DirectQuery before anything distributed |
| Security bugs (data leak across RLS / workspaces) | RLS applied in the planner, not in visuals; cache keyed by RLS context; query endpoint accepts names only; tests that try to escape RLS with `ALL()` |
| Long-term maintenance | Small number of contracts (§4); engine is a library with tests; no custom DSLs beyond DAX-lite |

### Build vs adopt

| Option | Verdict |
|---|---|
| Keep Power BI, buy Fabric capacity | Lowest effort; keeps cost, iframe, gateway and two security systems |
| Apache Superset | Strong open-source BI, SQL-centric; no DAX-like model layer, different UX from Power BI, theming/embedding effort |
| Metabase | Very easy for simple questions; weak semantic model; limited report layout |
| Cube + own front end | Good semantic layer; its own YAML/JS modelling, no DAX-like language |
| **Own v2 (this document)** | Most work, but the only option giving a Power BI–like modelling and authoring experience that we own, theme, embed natively and extend |

**Recommendation.** Build it, engine first. Phase 1 has no UI on purpose: if the
planner and DAX-lite can reproduce MSD's existing dashboards number for number,
the rest is product engineering with a known target. If they can't, we find out
in six weeks, not six months.
