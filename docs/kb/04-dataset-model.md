# 04 — Dataset & Semantic Model

> **Status: Implemented in MAGBI-003 (Sprint 3), with the limits below**

The stored document is snake_case JSON in `datasets.definition`. Identity,
timestamps, and `current_version` stay on the row. `model_version` is the
optimistic concurrency counter. The examples further down keep the spec's
camelCase names; the API and the Pydantic models use snake_case (`schema_version`,
`data_type`, `is_primary_key`, `connection_id`).

What this sprint stores and checks:

- Tables, columns, measures, calculated columns, hierarchies, relationships, and
  RLS roles. Measures and calculated columns are text. RLS is stored and not enforced.
- Relationships are many-to-one or one-to-one only. Many-to-many and bidirectional
  cross-filter are rejected. One active relationship per pair of tables. The one
  side must be a primary key.
- Join paths are undirected over active relationships. Cycles are directed
  many-to-one. An ambiguous path is an error.
- A date table can be generated and is written into DuckDB on the next refresh
  when `date_table.auto_generate` is true.
- Validation reports structural errors and four warnings. Expression parsing and
  high-cardinality checks are deferred (`checks_deferred`).

Auto-detecting relationships and the model editor UI are not in this sprint.

---

## What It Does

A semantic model is the layer between raw database tables and the questions a
business user asks. Without it, every chart requires someone who can write SQL
joins, knows which column is the foreign key, and remembers that "revenue" means
`SUM(InvoiceLines.Qty * InvoiceLines.UnitPrice)`. With a semantic model, the
user drags "Revenue" onto a chart and the system figures out the rest.

In MagBI the semantic model is a single JSON document — the **Dataset
Definition** — that describes:

| Concept | What it captures |
|---------|-----------------|
| **Tables** | Which tables exist, where they come from, which columns they expose |
| **Columns** | Name, data type, visibility, sort order |
| **Measures** | Named DAX-lite formulas that define how to aggregate data |
| **Relationships** | How tables join — foreign-key links with cardinality and direction |
| **Hierarchies** | Drill-down paths (e.g., Year → Quarter → Month → Day) |
| **Date tables** | Special tables the time-intelligence engine relies on |
| **RLS roles** | Row-level security rules that restrict who sees which rows |

Every other component in MagBI reads this document: the query engine uses it to
resolve joins and compile measures; the report designer uses it to populate the
data pane; the embed API uses it to enforce RLS. One file, many consumers.

---

## Why This Approach

### JSON over a relational schema

We could have stored the model in PostgreSQL tables (`t_tables`, `t_columns`,
`t_relationships`, etc.) and queried them with SQL. Instead, the model is a
single JSON document stored as a JSONB column in the `datasets` metadata table.

**Reasons:**

1. **Atomic reads.** The query engine needs the entire model to plan a query.
   Reading one JSON blob is one I/O operation; reading six relational tables
   with joins is six.
2. **Versioning.** Storing the model as a document makes it trivial to keep
   old versions — each refresh can snapshot the model as-is.
3. **Portability.** A dataset can be exported as a single JSON file and
   imported into another MagBI instance. No schema migration needed.
4. **Frontend alignment.** The report designer already works with JSON. Having
   the model in the same format means the frontend can display and edit it
   without an ORM translation layer.

**Trade-off:** JSON loses referential integrity. A measure can reference a table
that does not exist. We compensate with **model validation** (see below) — a
set of 22 checks run before the model is saved.

### Star schema by convention, not enforcement

MagBI expects — but does not enforce — a star schema: one or more **fact tables**
(transactions, events, measurements) surrounded by **dimension tables**
(customers, products, dates). Relationships point from fact to dimension
(many-to-one).

We do not enforce this because:
- Some datasets have a single table (a flat CSV). That is fine.
- Some datasets have snowflake schemas (dimensions joining to other dimensions).
  That works too.
- Enforcing star schema rejects valid use cases for no benefit.

The query engine handles any topology, but performs best with star schemas
because the join resolution algorithm (BFS from dimensions to facts) is
optimised for that shape.

---

## How It Works

### DatasetDefinition — the root object

```typescript
interface DatasetDefinition {
  schemaVersion: string;      // "1.0" — for future migration
  name: string;               // Human-readable name
  tables: TableDefinition[];
  relationships: RelationshipDefinition[];
  measures: MeasureDefinition[];
  roles?: RlsRoleDefinition[];
}
```

Everything hangs off this root. The `schemaVersion` field lets us evolve the
format without breaking existing datasets — a future version can read old
formats and migrate them.

### Tables and columns

```typescript
interface TableDefinition {
  name: string;
  source: TableSource;
  columns: ColumnDefinition[];
  isDateTable?: boolean;
}

type TableSource =
  | { type: "sqlTable"; schema: string; table: string }
  | { type: "sqlQuery"; query: string }
  | { type: "csv"; filePath: string };

interface ColumnDefinition {
  name: string;
  dataType: "string" | "integer" | "decimal" | "boolean"
          | "dateTime" | "date" | "time" | "binary";
  isHidden?: boolean;
  sortByColumn?: string;  // e.g., MonthName sorted by MonthNumber
}
```

**`TableSource` is a discriminated union.** The `type` field tells the import
pipeline how to read the data. A `sqlTable` source reads directly from a
database table. A `sqlQuery` source runs a custom SQL query. A `csv` source
reads a file. This is the Strategy pattern again — the import pipeline
dispatches on the `type` field.

**`sortByColumn`** is a BI-specific concept. In a chart, "January, February, ...
December" should appear in calendar order, not alphabetical. `sortByColumn`
tells the query engine to `ORDER BY MonthNumber` even when the user drags
`MonthName` onto the axis. Power BI calls this "Sort by column."

**Eight data types.** These map to every source database's type system:

| MagBI type | SQL Server | PostgreSQL | MySQL | DuckDB |
|-----------|-----------|-----------|-------|--------|
| string | nvarchar, varchar, char | text, varchar, char | varchar, text | VARCHAR |
| integer | int, bigint, smallint | integer, bigint | int, bigint | INTEGER, BIGINT |
| decimal | decimal, float, money | numeric, real, double | decimal, float | DECIMAL, DOUBLE |
| boolean | bit | boolean | tinyint(1) | BOOLEAN |
| dateTime | datetime, datetime2 | timestamp | datetime | TIMESTAMP |
| date | date | date | date | DATE |
| time | time | time | time | TIME |
| binary | varbinary | bytea | blob | BLOB |

The mapping is lossy — SQL Server's `MONEY` type becomes `decimal` and loses its
currency semantics. This is acceptable because MagBI's format strings handle
currency display, and the underlying value is still a decimal.

### Measures

```typescript
interface MeasureDefinition {
  name: string;
  table: string;        // "home table" — where the measure lives conceptually
  expression: string;   // DAX-lite formula, e.g., "SUM(Sales[Amount])"
  formatString?: string;
  description?: string;
}
```

A measure is a named calculation. Unlike a column (which has one value per row),
a measure produces one value per group. `SUM(Sales[Amount])` returns a different
number depending on whether the chart groups by month, by customer, or by
product.

**Home table:** Every measure belongs to a table. This is a UI convenience — the
data pane shows measures under their home table. The query engine does not care;
it resolves the measure's expression against the full model.

**Implicit measures:** When a user drags a numeric column onto the Values well
without writing a formula, the designer creates an implicit measure —
`SUM(TableName[ColumnName])` by default. The user can change the aggregation
to COUNT, AVERAGE, MIN, MAX, or DISTINCTCOUNT via the well chip dropdown.

### Relationships

```typescript
interface RelationshipDefinition {
  fromTable: string;    // The "many" side (typically the fact table)
  fromColumn: string;
  toTable: string;      // The "one" side (typically the dimension table)
  toColumn: string;
  cardinality: "manyToOne" | "oneToOne";
  crossFilterDirection: "single" | "both";
  isActive: boolean;
  joinType: "inner" | "left";
}
```

**Cardinality** tells the query engine what kind of join to generate. `manyToOne`
is the standard fact-to-dimension relationship — many sales rows reference one
customer. `oneToOne` is rarer (e.g., Employee to EmployeeDetails).

**Cross-filter direction** controls how filters flow through the relationship.
`single` means filters flow from the "one" side to the "many" side only (from
dimension to fact). `both` means filters flow in both directions — this enables
"bidirectional cross-filtering," where clicking on a fact filters the dimension.

**Why `single` is the default:** Bidirectional filtering is powerful but
dangerous. It can create circular filter paths in complex models, producing
ambiguous or incorrect results. We default to `single` and require the user to
opt into `both` per relationship.

**Active vs. inactive:** Only one active relationship can exist between any
two tables. If multiple join paths exist (e.g., Sales→OrderDate and
Sales→ShipDate both linking to a Date table), one is active (used by default)
and the others are inactive (used only when explicitly invoked via
`USERELATIONSHIP` in a DAX measure).

**Join type:** `left` is the default — every fact row appears even if it has no
matching dimension row (the dimension columns are NULL). `inner` drops fact rows
with no match. Most BI tools use `left` by default because dropping data
silently is worse than showing a "blank" dimension value.

### Auto-detect relationships

When a user imports tables, MagBI looks for matching column names between
tables. If `Sales` has a column `CustomerID` and `Customers` has a column
`CustomerID`, and `Customers.CustomerID` is unique, MagBI suggests a
many-to-one relationship from `Sales.CustomerID` to `Customers.CustomerID`.

**The algorithm:**

1. For each pair of tables (A, B):
2. For each column in A, find columns in B with the same name
3. If the column in B has unique values (checked during import), suggest
   A.col → B.col as many-to-one
4. Present suggestions to the user for confirmation

**Why confirmation, not auto-creation:** Column name matching produces false
positives. A column named `Name` in two unrelated tables does not mean they
should be joined. The user reviews suggestions and accepts or rejects each one.

### Date tables

Time intelligence in BI (year-over-year comparisons, running totals, fiscal
periods) requires a contiguous date table — one row per day with no gaps, from
the earliest date in the data to the latest.

**Why BI needs dedicated date tables:**

SQL date functions (`DATEADD`, `DATEDIFF`) work on individual values. But BI
time intelligence works on *ranges* — "all dates in the same month last year."
To compute this, you need a table where you can filter to a range of dates and
then shift that range. Without a date table, you cannot express "same period
last year" as a filter operation.

**Auto-generated date table:**

When the user marks a table as a date table (or MagBI auto-detects one), the
system generates 15 columns:

| Column | Example | Purpose |
|--------|---------|---------|
| Date | 2026-03-15 | The primary key |
| Year | 2026 | Group by year |
| Quarter | Q1 | Group by quarter |
| QuarterNumber | 1 | Sort quarter correctly |
| Month | March | Group by month name |
| MonthNumber | 3 | Sort month correctly |
| Day | 15 | Day of month |
| DayOfWeek | Sunday | Day name |
| DayOfWeekNumber | 0 | Sort day correctly |
| WeekNumber | 11 | ISO week number |
| YearMonth | 2026-03 | Combined sort key |
| YearQuarter | 2026-Q1 | Combined sort key |
| FiscalYear | FY2026 | Fiscal year (configurable start month) |
| FiscalQuarter | FQ3 | Fiscal quarter |
| IsCurrentMonth | true | Highlight convenience |

**Fiscal year support:** Many organisations have fiscal years that do not start
in January. MagBI lets the user configure the fiscal year start month. If the
fiscal year starts in July, then July 2026 is FY2027-Q1.

### Hierarchies

A hierarchy defines a drill-down path: Year → Quarter → Month → Day, or
Country → Region → City. In the data pane, hierarchies appear as expandable
tree nodes. When the user drags a hierarchy onto an axis, the chart shows the
top level and lets the user drill down.

```typescript
interface HierarchyDefinition {
  name: string;
  table: string;
  levels: string[];  // Column names, from coarsest to finest
}
```

Hierarchies are pure UI metadata — they do not affect the query engine. When the
user drills from Year to Quarter, the designer replaces `Year` with `Quarter` in
the semantic query.

### Row-Level Security (RLS)

RLS restricts which rows a user can see. An HR manager sees all employee data;
a department head sees only their department's data.

```typescript
interface RlsRoleDefinition {
  name: string;
  filters: Array<{
    table: string;
    expression: string;  // DAX-lite filter, e.g., "[Department] = @UserDepartment"
  }>;
}
```

**How RLS works:**

1. An admin creates a role (e.g., "DepartmentHead") with a filter:
   `[Department] = @UserDepartment`
2. The admin assigns users to the role with a parameter:
   `{user: "alice", UserDepartment: "Finance"}`
3. When Alice queries the dataset, the query engine injects
   `WHERE Department = 'Finance'` into every sub-query
4. Alice sees only Finance data — every chart, every table, every card

**The `@` parameters:** RLS expressions can reference dynamic parameters
(prefixed with `@`). These are resolved at query time from the user's role
assignment. This avoids creating one role per department — a single role
definition with `@UserDepartment` works for all departments.

**Security invariant:** RLS filters are injected at the SQL level and are
**never removable** by DAX functions like `ALL()` or `REMOVEFILTERS()`. If a
measure uses `CALCULATE(SUM(Amount), ALL(Department))`, the ALL removes the
user's filter on Department — but the RLS filter stays. This is critical for
security: a measure author cannot accidentally (or maliciously) bypass RLS.

**"View as role" testing:** The model editor lets an admin preview the data as
if they were assigned to a specific role. This is essential for testing RLS
rules before publishing.

### Model validation

Before saving, the model runs through 22 validation checks:

**16 errors (block save):**
- Duplicate table names
- Duplicate column names within a table
- Duplicate measure names within a table
- Relationship references non-existent table or column
- Multiple active relationships between the same two tables
- Circular relationship paths (A→B→C→A)
- Measure expression fails to parse
- RLS expression fails to parse
- Date table has gaps (missing dates)
- Date table primary key is not unique
- Date table does not cover the data range
- Calculated column expression references non-existent column
- Calculated column circular dependency
- sortByColumn references non-existent column
- Hierarchy references non-existent column
- Hierarchy has fewer than 2 levels

**6 warnings (allow save with notification):**
- Table has no relationships (orphan table)
- Bidirectional cross-filtering enabled (may cause ambiguity)
- Measure has no format string
- Column marked as hidden but used in no measure
- Relationship uses inner join (may drop data)
- Date table has no fiscal year configuration

---

## The Model Editor UI

### Diagram view

The model editor's primary view is a **force-directed diagram** — tables are
boxes connected by lines representing relationships. The layout uses a
force-simulation algorithm (similar to D3's force layout):

- Tables repel each other (to avoid overlap)
- Relationships act as springs (connected tables stay close)
- The user can drag tables to override the automatic layout

Each table box shows:
- Table name (header)
- Column list (with type icons)
- Measures (with Σ icon)
- Relationship endpoints (connection dots)

### Measure editor

Clicking a measure opens the **Monaco Editor** (the same editor engine as VS
Code) with DAX-lite syntax highlighting, autocomplete, and error squiggles.

**Why Monaco:** It provides IntelliSense-quality editing in the browser — syntax
highlighting, bracket matching, multi-cursor, find/replace, and extensible
language services. We register a DAX-lite language definition that highlights
keywords, function names, table references, and column references.

### Schema drift detection

When a dataset is refreshed, the source tables may have changed — columns added,
removed, or type-changed. MagBI detects these changes and reports them:

| Change | Impact | Action |
|--------|--------|--------|
| Column added | None (new column is not in the model) | Notify user; they can add it |
| Column removed | Measures/relationships referencing it break | Error; user must fix model |
| Column type changed | May break type-dependent measures | Warning; user reviews |

---

## Key Concepts

### The star schema

The star schema is the dominant pattern in analytical databases. Named for its
shape when diagrammed — a central fact table with dimension tables radiating
outward like points of a star.

```
          ┌──────────┐
          │  Product  │
          └─────┬────┘
                │
┌─────────┐    │    ┌──────────┐
│ Customer ├────┼────┤  Sales   │
└─────────┘    │    │  (fact)  │
                │    └────┬─────┘
          ┌─────┴────┐    │
          │   Date   │    │
          └──────────┘    │
                    ┌─────┴────┐
                    │  Store   │
                    └──────────┘
```

**Why it works for BI:**
- Every query joins facts to dimensions (many-to-one) — simple, predictable joins
- Aggregations happen on the fact table; dimensions provide labels and filters
- The query engine can optimise for this pattern (group by dimensions, aggregate
  facts)

**Snowflake schema** is a variation where dimensions join to other dimensions
(e.g., Product → Category → Department). MagBI supports this but the query
engine is optimised for star.

### Many-to-many relationships

MagBI does NOT support direct many-to-many relationships (e.g., Students ↔
Courses). This is a deliberate limitation shared with Power BI's import mode.

**Why:** Many-to-many relationships create ambiguous aggregations. If Student A
takes Courses X and Y, and you ask "total students per course," the answer
depends on whether you count A once or twice. There is no universally correct
answer without additional context.

**The workaround: bridge tables.** Create a table `StudentCourses` with one row
per (Student, Course) pair. Now you have two many-to-one relationships:
Students → StudentCourses ← Courses. The aggregation semantics become explicit.

### Calculated columns vs. measures

| | Calculated Column | Measure |
|---|---|---|
| **When computed** | At refresh time (stored in DuckDB) | At query time (on each query) |
| **Result** | One value per row | One value per group |
| **Storage** | Takes disk space | Zero storage |
| **Can reference** | Other columns in the same row | Any column, via aggregation |
| **Can be filtered** | Yes (it is a column) | No (it produces an aggregate) |

**When to use each:**
- Calculated column: classification (`IF [Amount] > 1000, "Large", "Small"`)
  — needs to be filterable, and the expression is simple
- Measure: aggregation (`SUM`, `AVERAGE`, year-over-year comparison) — depends
  on the query context

---

## Strengths

- **Single JSON document** drives the entire system — query engine, designer,
  embed viewer, and admin UI all read the same model
- **Validation catches errors early** — broken measures, circular relationships,
  and invalid RLS are caught before the model is published
- **RLS is security-enforced** — filters are injected at the SQL level and
  cannot be removed by DAX formulas
- **Auto-detect relationships** reduce manual modelling for simple datasets
- **Date table auto-generation** means time intelligence works out of the box

## Weaknesses & Risks

- **No many-to-many without bridge tables** — power users coming from Tableau
  (which handles M2M natively) will find this limiting
- **Calculated columns compute at refresh time** — if the source data changes
  between refreshes, calculated columns are stale
- **JSON document can grow large** — a dataset with 200 tables and 5000 columns
  produces a multi-MB JSON document. Parsing and validation take time.
- **Model editor is complex** — the force-directed diagram, Monaco editor, and
  relationship dialog are among the most complex UI components in MagBI
- **Schema drift can break production dashboards** — a DBA renaming a column in
  the source database breaks every measure referencing that column. MagBI detects
  this but cannot auto-fix it.

---

## For Agents

1. The stored model is `server/magbi/model/schema.py` (snake_case JSON in
   `datasets.definition`). `web/src/types/dataset.ts` still follows this spec's
   camelCase and is not what the API returns. Do not treat the two files as
   the same schema until the UI sprint maps them.
2. Relationships are a directed graph. The query engine traverses this graph
   via BFS (see chapter 06). Do not create cycles.
3. RLS filters are appended to the `WHERE` clause of every sub-query. They
   MUST NOT be removable. If you touch the query engine, verify that
   `ALL()` and `REMOVEFILTERS()` do not strip RLS.
4. Model validation runs in `server/magbi/model/validation.py`. When adding
   a new model feature, add validation rules for it.
5. The model editor UI components are in `web/src/model-editor/`. The diagram
   uses force-directed layout; do not switch to a grid layout without discussion.

---

## Further Reading

- [Star Schema (Kimball Group)](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/star-schema-olap/)
- [Power BI data modelling guide](https://learn.microsoft.com/en-us/power-bi/guidance/star-schema)
- [Row-Level Security in analytical systems](https://learn.microsoft.com/en-us/power-bi/enterprise/service-admin-rls)
- [Force-directed graph drawing](https://en.wikipedia.org/wiki/Force-directed_graph_drawing)
- [Monaco Editor](https://microsoft.github.io/monaco-editor/)
- [JSON Schema specification](https://json-schema.org/)
