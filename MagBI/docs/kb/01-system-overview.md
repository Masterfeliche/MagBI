# 01 — System Overview

> **Status: Planned**

---

## What MagBI Is

MagBI is a general-purpose business intelligence engine. An analyst connects to
a database, shapes the data, builds a semantic model with measures and
relationships, designs a report by dragging visuals onto a canvas, publishes it,
and shares it — either as a standalone app or embedded inside another product
via an iframe.

That sentence describes what Power BI, Tableau, Looker, Metabase, and Superset
all do. MagBI is our own implementation of the same idea, built from scratch so
that we own every layer, can embed it deeply into products like the MSD ERP, and
can evolve it without per-user licensing costs.

### The core loop

```
Data Source → Connect → Transform → Model → Measure → Design → Publish → View
```

Every BI tool implements this loop. The differences are in *how* each step
works, what trade-offs it makes, and how well the steps compose. This knowledge
base walks through each step in MagBI.

---

## Why Build a BI Engine From Scratch

### The licensing problem

Commercial BI tools charge per user per month. For an ERP with hundreds of
internal users who need dashboards, this cost compounds. Embedding Power BI
inside another product requires Power BI Embedded capacity, which has its own
pricing tier and constraints.

### The integration problem

Embedding a third-party BI tool means living inside its iframe, its
authentication model, its theming constraints, and its API limitations. When the
ERP needs a dashboard to react to a sidebar click or pass row-level security
from its own user system, the integration becomes fragile glue code.

### The learning problem

Building a BI engine is one of the best ways to learn how modern data systems
work — from query engines to formula languages to interactive visualization.
This project is as much a learning vehicle as a product.

### What we are NOT building

- Not a data warehouse (we read from existing databases)
- Not an ETL pipeline (we do light transforms, not enterprise ETL)
- Not a notebook environment (no Python/R cells)
- Not a real-time streaming engine (we refresh periodically)

---

## Architecture Big Picture

```
┌─────────────────────────────────────────────────────────┐
│                        Browser                          │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐            │
│  │ Designer │  │  Viewer  │  │Model Editor│            │
│  └────┬─────┘  └────┬─────┘  └─────┬─────┘            │
│       └──────────────┼──────────────┘                  │
│                      │ REST / WebSocket                │
└──────────────────────┼─────────────────────────────────┘
                       │
┌──────────────────────┼─────────────────────────────────┐
│                  FastAPI Server                         │
│  ┌─────┐  ┌───────┐  ┌──────┐  ┌────────┐            │
│  │ API │  │ Auth  │  │Engine│  │Refresh │            │
│  └──┬──┘  └───┬───┘  └──┬───┘  └───┬────┘            │
│     │         │         │           │                  │
│  ┌──┴─────────┴─────────┴───────────┴──┐              │
│  │         DAX-lite Compiler           │              │
│  └──┬──────────────────────────────┬───┘              │
│     │                              │                  │
│  ┌──┴───────┐              ┌───────┴──┐               │
│  │  sqlglot │              │ DuckDB   │               │
│  └──────────┘              └──────────┘               │
└────────────────────────────────────────────────────────┘
         │                        │
    ┌────┴────┐              ┌────┴────┐
    │PostgreSQL│              │ Redis  │
    │(metadata)│              │(cache) │
    └─────────┘              └────────┘
```

### The three data stores

| Store | What it holds | Why this technology |
|-------|--------------|---------------------|
| **DuckDB** | Imported analytical data (one `.duckdb` file per dataset version) | Column-oriented, in-process, fast analytical queries, no server to manage |
| **PostgreSQL** | Metadata — workspaces, datasets, reports, users, audit log | Mature relational DB for transactional metadata; every team knows Postgres |
| **Redis** | Query result cache, refresh job queue, WebSocket pub/sub | In-memory speed for caching; built-in pub/sub for real-time events |

### The two runtimes

| Runtime | Technology | Role |
|---------|-----------|------|
| **API server** | Python + FastAPI | Handles HTTP requests, runs the query engine, serves the embed viewer |
| **Worker** | Python + Celery (or ARQ) | Runs background data refresh jobs — connects to sources, imports data |

---

## Technology Stack — Why Each Choice

### Python (server)

**Why:** The data ecosystem lives in Python — DuckDB's best bindings are Python,
sqlglot is Python, pandas/polars for transforms are Python. Using Python means
every library we need is a `pip install` away.

**Strengths:**
- Massive ecosystem for data processing
- FastAPI gives us async HTTP with automatic OpenAPI docs
- Easy to prototype and iterate quickly
- sqlglot and DuckDB have first-class Python APIs

**Weaknesses:**
- Slower than Go/Rust for CPU-bound work (but our hot path is DuckDB, which
  is C++)
- GIL limits true parallelism (mitigated by async I/O and Celery workers)
- Type system is optional (we use strict mypy to compensate)

**Alternatives rejected:**
- **Go** — Great for servers, but poor data library ecosystem. We would have to
  shell out to Python for DuckDB/sqlglot anyway.
- **Rust** — Maximum performance, but much slower to iterate. The team knows
  Python; Rust would triple development time.
- **Node.js** — Possible, but DuckDB and sqlglot bindings are Python-first.
  TypeScript on the server would mean maintaining two different type systems.

### React + TypeScript (frontend)

**Why:** The report designer is a complex interactive application — free-form
canvas, drag-and-drop, property editors, real-time chart rendering. React's
component model handles this well, and TypeScript catches bugs at compile time
that would otherwise surface as runtime crashes in the designer.

**Strengths:**
- Largest ecosystem of UI libraries (dnd-kit, TanStack Table, Monaco Editor)
- TypeScript gives us typed contracts that match the server's API
- Component model maps naturally to visual types
- Vite gives sub-second hot reload during development

**Weaknesses:**
- Bundle size can grow large (mitigated by code splitting per route)
- React's re-rendering model needs care in the canvas (many visuals updating)
- State management complexity (mitigated by Zustand, which is simpler than Redux)

**Alternatives rejected:**
- **Vue** — Excellent framework, but smaller ecosystem for the specific
  libraries we need (dnd-kit has no Vue equivalent at the same quality).
- **Svelte** — Great performance, but the ecosystem is still maturing. For a
  complex designer app, we need battle-tested libraries.
- **Vanilla JS** — Maximum control, but we would spend months building what
  React gives us out of the box (component lifecycle, state management, etc.)

### DuckDB (analytical storage)

**Why:** DuckDB is to analytics what SQLite is to applications — an in-process
database that needs no server. Each dataset becomes a single `.duckdb` file.
The query engine opens it, runs SQL, and closes it. No connection pooling, no
server process, no network latency between the query engine and the data.

**Strengths:**
- Columnar storage = fast aggregations (the bread and butter of BI)
- In-process = zero network overhead for queries
- Excellent SQL dialect with window functions, CTEs, GROUPING SETS
- File-based = atomic swap for zero-downtime refresh (rename the file)
- Parquet import/export built in

**Weaknesses:**
- Single-writer limitation (only one process can write at a time)
- Not designed for high-concurrency OLTP (but we only do analytical reads)
- Memory usage can spike on large joins (mitigated by memory limits in config)
- No built-in replication (we handle this at the file level)

**Alternatives rejected:**
- **ClickHouse** — Excellent analytical DB, but requires a running server.
  Adds operational complexity for what is often a single-tenant deployment.
- **Apache Arrow / DataFusion** — Promising, but less mature SQL support and
  no built-in persistent storage.
- **SQLite** — Row-oriented, so analytical queries on millions of rows are
  10-100x slower than DuckDB's columnar format.
- **PostgreSQL (for analytics too)** — We could put analytical data in Postgres,
  but columnar aggregation in Postgres is significantly slower than DuckDB for
  the query patterns BI generates.

### sqlglot (SQL generation and transpilation)

**Why:** The DAX-lite compiler needs to produce SQL. The same SQL must work on
DuckDB (for imported data) and potentially on SQL Server / PostgreSQL (for
DirectQuery). sqlglot is a Python library that can parse SQL into an AST,
transform it, and output it in any dialect.

**Strengths:**
- Dialect-aware: generate DuckDB SQL, T-SQL, or PostgreSQL from the same IR
- Pure Python, no native dependencies
- Can also parse source SQL (useful for query folding in transforms)
- Active maintenance and large test suite

**Weaknesses:**
- Some edge cases in dialect transpilation (obscure T-SQL features)
- Performance overhead for very complex queries (mitigated by caching)
- Learning curve for the AST API

**Alternatives rejected:**
- **String concatenation** — Error-prone, no parameterisation, no dialect support.
  Every BI tool that started this way eventually rewrote it.
- **SQLAlchemy Core** — Good for building queries, but not designed for
  transpiling between dialects.
- **Jinja SQL templates** — Readable for simple cases, but unmaintainable for
  the complex nested queries that CALCULATE generates.

### ECharts (visualization)

**Why:** ECharts renders 17+ chart types from a single declarative JSON
configuration. No SVG path manipulation, no D3 bindng boilerplate — pass an
option object and ECharts draws it. This maps perfectly to a BI tool where
each visual type is a function from (data + bindings) → chart config.

**Strengths:**
- Declarative API: `setOption(json)` renders any chart
- Canvas + SVG dual rendering (Canvas for performance, SVG for export)
- Built-in animations, tooltips, legends, zoom, brush selection
- 50k+ GitHub stars, actively maintained by Apache
- Dataset/encode model decouples data from visual mapping

**Weaknesses:**
- Large bundle (~800KB minified, but tree-shakeable)
- Customisation beyond the option API requires custom series (rare but complex)
- Documentation is extensive but sometimes hard to navigate
- Theming is powerful but the API surface is large

**Alternatives rejected:**
- **D3.js** — Maximum flexibility, but you build everything from primitives.
  A bar chart in D3 is 50+ lines; in ECharts it is a JSON object. For 14
  visual types, D3 would multiply development time by 5x.
- **Chart.js** — Simpler API but fewer chart types and less powerful than
  ECharts for matrix/treemap/funnel/waterfall.
- **Recharts** — React wrapper around D3, limited to basic chart types.
- **Plotly** — Good for notebooks, but heavy and opinionated for embedding.

---

## Design Principles

These principles guide every decision in MagBI:

### 1. Contracts over code

The system is held together by three JSON contracts:
- **Dataset Definition** — describes what data exists and how it relates
- **Semantic Query** — describes what data to fetch
- **Report Definition** — describes what to show on screen

Any component that respects these contracts can be replaced. The frontend does
not know how the query engine works; the query engine does not know what the
frontend looks like. This is the most important architectural decision in the
system.

### 2. Compile, don't interpret

DAX-lite formulas compile to SQL. Transform steps compile to SQL (query
folding). The query engine builds SQL and hands it to DuckDB. We never
interpret formulas row-by-row in Python — that would be 1000x slower.

### 3. Files over services

Datasets are DuckDB files. Reports are JSON files (in the metadata DB, but
conceptually files). The system can run with just the filesystem — PostgreSQL
and Redis are for multi-user features, not core functionality.

### 4. One writer, many readers

DuckDB files have one writer (the refresh worker) and many readers (the query
engine). This avoids all the complexity of concurrent writes, locking, and
transactions in the analytical store.

### 5. Fail visibly

When a query fails, the visual shows the error, not a spinner. When a refresh
fails, the old data stays live and the failure is logged. The system never
silently drops data or shows stale results without indicating it.

### 6. Progressive complexity

A new user can connect a CSV, see a chart, and publish it in minutes. The
semantic model, DAX formulas, and RLS are there when they need them — but the
simplest path does not require them.

---

## Key Concepts for Learning

### What is a semantic model?

A semantic model sits between raw database tables and the user's questions.
Instead of writing SQL like `SELECT dept, SUM(amount) FROM invoices JOIN
departments ON ...`, the user drags "Department" and "Total Amount" onto a chart.
The semantic model knows:
- Which tables exist and how they relate (via foreign keys / relationships)
- What "Total Amount" means (it is `SUM(InvoiceAmount)`, defined once)
- Who can see what data (row-level security)

Power BI calls this a "dataset." Looker calls it "LookML." Tableau calls it a
"data source." The concept is the same: an abstraction layer that lets business
users ask questions without writing SQL.

### What is a formula language?

Power BI has DAX. Tableau has LOD expressions. Looker has LookML measures.
These are all mini-languages that define *how to aggregate data*. They exist
because SQL alone cannot express some common BI calculations concisely:

- "Revenue this year vs. last year" (time intelligence)
- "Each product's share of total revenue" (CALCULATE with ALL)
- "Running total across months" (window functions with context)

DAX-lite is MagBI's formula language. It uses DAX syntax (familiar to Power BI
users) but compiles to SQL (because our execution engine is DuckDB, not a
custom engine).

### What is query folding?

When you apply transforms to data (filter rows, change types, add columns),
those transforms can either run in Python (slow, processes all rows in memory)
or be "folded" into the SQL query sent to the source database (fast, the
database does the work). Query folding is the compiler optimisation that
converts transform steps into SQL.

### What is an analytical (columnar) database?

Traditional databases (PostgreSQL, MySQL, SQL Server) store data row by row.
This is great for looking up one customer's order, but slow for "sum all orders
by month for the last 3 years" because the database must read every column of
every row even though it only needs the date and amount columns.

Columnar databases (DuckDB, ClickHouse, Redshift) store data column by column.
Summing a column means reading just that column's data — often 10-100x faster
for the aggregation queries that BI tools generate.

### What is cross-filtering?

In a BI dashboard, clicking a bar in one chart filters all other charts on the
page. This is cross-filtering. It means:
1. The user clicks "Q3" on a revenue chart
2. The designer emits a filter: `Quarter = Q3`
3. All other visuals on the page re-query with that filter added
4. The charts update to show only Q3 data

This creates the interactive, exploratory experience that makes dashboards
useful — the user "drills in" by clicking, without writing any query.

---

## For Agents

If you are an AI agent working on MagBI:

1. **Read the chapter for your layer** before writing code.
2. **Respect the three contracts** — dataset definition, semantic query, report
   definition. Do not add fields to these without updating both the chapter and
   the TypeScript types.
3. **Compile to SQL, never interpret in Python.** If you find yourself writing a
   for-loop over rows, stop and think about whether this should be a SQL query.
4. **Run the tests.** Each server package has its own test directory. Add tests
   for new functionality.
5. **Update this knowledge base** when you implement something that changes the
   design. The chapter should reflect what the code actually does, not just the
   plan.

---

## Further Reading

- [Power BI Architecture Whitepaper (Microsoft)](https://learn.microsoft.com/en-us/power-bi/guidance/power-bi-optimization)
- [The Semantic Lakehouse (Databricks)](https://www.databricks.com/glossary/semantic-layer)
- [DuckDB: An Embeddable Analytical Database](https://duckdb.org/why_duckdb)
- [sqlglot Documentation](https://sqlglot.com/)
- [ECharts Handbook](https://apache.github.io/echarts-handbook/)
- [Designing Data-Intensive Applications (Martin Kleppmann)](https://dataintensive.net/) — the
  definitive book on the ideas behind every store and pipeline in this system
