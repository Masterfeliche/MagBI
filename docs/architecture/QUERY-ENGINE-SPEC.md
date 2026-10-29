# Query engine specification

How a visual's question becomes SQL, runs on DuckDB, and returns rows. This is
the runtime heart of v2: the component that sits between the report viewer and
the data. Everything in the DAX-lite spec (compilation rules, filter context,
CALCULATE, time intelligence) is implemented here.

| | |
|---|---|
| Written | 29 October 2026 |
| Status | Draft — not implemented |
| Depends on | [DAX-LITE-SPEC.md](DAX-LITE-SPEC.md), [POWERBI-V2-ARCHITECTURE.md](POWERBI-V2-ARCHITECTURE.md) §10 |
| Reference engines | Power BI (formula engine + storage engine), Cube.js (semantic → SQL), Apache Superset (dataset → SQLAlchemy), DuckDB (optimizer) |

---

## Contents

1. [What the query engine does](#1-what-the-query-engine-does)
2. [The semantic query contract](#2-the-semantic-query-contract)
3. [End-to-end pipeline](#3-end-to-end-pipeline)
4. [Step 1: Parse and bind](#4-step-1-parse-and-bind)
5. [Step 2: Build the filter context](#5-step-2-build-the-filter-context)
6. [Step 3: Expand measures](#6-step-3-expand-measures)
7. [Step 4: Resolve relationships and joins](#7-step-4-resolve-relationships-and-joins)
8. [Step 5: Plan sub-queries (home-table grouping)](#8-step-5-plan-sub-queries-home-table-grouping)
9. [Step 6: Generate SQL with sqlglot](#9-step-6-generate-sql-with-sqlglot)
10. [Step 7: Execute on DuckDB](#10-step-7-execute-on-duckdb)
11. [Step 8: Post-process (blank-row removal, totals, formatting)](#11-step-8-post-process)
12. [The query result contract (DSR)](#12-the-query-result-contract-dsr)
13. [Caching](#13-caching)
14. [Security: RLS injection](#14-security-rls-injection)
15. [DirectQuery mode](#15-directquery-mode)
16. [Query limits and timeouts](#16-query-limits-and-timeouts)
17. [Observability](#17-observability)
18. [Worked examples](#18-worked-examples)

---

## 1. What the query engine does

A visual in a report never issues SQL. It sends a **semantic query** — a
declarative JSON object saying "I need these measures, grouped by these
columns, under these filters." The query engine:

1. Validates the query against the dataset model (tables, columns, measures,
   relationships, types).
2. Compiles every measure reference into its SQL equivalent (following the
   DAX-lite spec).
3. Figures out which tables to join and in what order.
4. Groups measures by their **home table** (the fact table they aggregate)
   to avoid fan-out / chasm traps.
5. Generates one or more SQL statements using sqlglot.
6. Executes them on DuckDB (Import mode) or the source database (DirectQuery).
7. Post-processes: removes blank rows, computes totals, formats values.
8. Returns a **DataShapeResult (DSR)** — a compact columnar JSON response the
   visual runtime consumes.

The visual never sees SQL. The report designer never sees SQL. Only the engine
internals and the observability layer deal with SQL.

---

## 2. The semantic query contract

Every query from a visual or the API is a `SemanticQuery` JSON object:

```jsonc
{
  // Version for forward compatibility
  "version": 2,

  // What to return — each entry is a column in the result
  "select": [
    // A dimension (groupBy column)
    {
      "type": "column",
      "table": "Directorate",
      "column": "Name",
      "alias": "Directorate"       // optional display name
    },
    // A measure
    {
      "type": "measure",
      "measure": "Trips",          // name from the model
      "alias": "Trips"
    },
    {
      "type": "measure",
      "measure": "Completion %"
    }
  ],

  // Filters applied before aggregation (WHERE-level)
  "filters": [
    {
      "table": "Date",
      "column": "Year",
      "op": "eq",
      "value": 2026
    },
    {
      "table": "Trip",
      "column": "Status",
      "op": "in",
      "values": ["Completed", "Approved", "In Progress"]
    }
  ],

  // Sort order
  "orderBy": [
    { "field": "Trips", "direction": "desc" }
  ],

  // Row limit (for Top-N visuals)
  "limit": 10,

  // Whether to include a totals row
  "includeTotals": true,

  // Whether to include subtotals (for matrix visuals with nested grouping)
  "includeSubtotals": false
}
```

### 2.1 Filter operators

| Operator | Meaning | SQL |
|---|---|---|
| `eq` | equals | `= value` |
| `neq` | not equals | `<> value` |
| `gt`, `gte`, `lt`, `lte` | comparisons | `>`, `>=`, `<`, `<=` |
| `in` | in set | `IN (values)` |
| `notIn` | not in set | `NOT IN (values)` |
| `between` | range (inclusive) | `BETWEEN value[0] AND value[1]` |
| `contains` | string contains | `LIKE '%value%'` |
| `startsWith` | string prefix | `LIKE 'value%'` |
| `isBlank` | is null | `IS NULL` |
| `isNotBlank` | is not null | `IS NOT NULL` |

### 2.2 Cross-filter queries

When a user clicks a bar in one visual to cross-filter others, the visual
emits a **cross-filter event** containing the clicked dimension values. The
report runtime adds these as extra filters to every other visual's semantic
query and re-queries them. The engine does not know about cross-filtering —
it just sees more filters.

### 2.3 What a visual sends vs what the engine receives

The visual wrapper (§ visuals doc) builds the `SemanticQuery` from its well
configuration:

```
Visual wells                    SemanticQuery
─────────────                   ─────────────
Axis: Directorate[Name]    →   select[0] = column(Directorate, Name)
Values: [Trips]             →   select[1] = measure(Trips)
Values: [Completion %]      →   select[2] = measure(Completion %)
Page filter: Year = 2026    →   filters[0] = { Date, Year, eq, 2026 }
Slicer: Status = Completed  →   filters[1] = { Trip, Status, in, [...] }
```

The engine receives the right-hand side. It never parses visual configuration.

---

## 3. End-to-end pipeline

```
SemanticQuery JSON
  │
  ▼ (1) Parse & Bind
  │  validate against model metadata
  │  resolve every table/column/measure name
  │
  ▼ (2) Build filter context
  │  merge: query filters + page filters + report filters + RLS predicates
  │  each filter targets one column → FilterContext map
  │
  ▼ (3) Expand measures
  │  inline each measure's DAX-lite AST
  │  recursively inline nested measure references
  │  detect circular dependencies
  │  resolve CALCULATE: apply filter replacements per §5 of DAX-lite spec
  │  resolve time intelligence: rewrite date ranges per §8
  │
  ▼ (4) Resolve relationships & joins
  │  for each column reference, find the JOIN path from its home fact table
  │  to the dimension table, through the relationship graph
  │  detect: no path, ambiguous paths, inactive relationships
  │
  ▼ (5) Plan sub-queries (home-table grouping)
  │  group measures by home fact table
  │  each group → one sub-query with its own FROM/JOIN/WHERE/GROUP BY
  │  measures with different filter contexts in the same group
  │    → FILTER (WHERE ...) clauses on the aggregate, or separate CTEs
  │
  ▼ (6) Generate SQL (sqlglot)
  │  IR nodes → sqlglot AST → dialect-specific SQL string
  │  one CTE per sub-query, combined with FULL OUTER JOIN on groupBy cols
  │  scalar expressions (DIVIDE, IF, SWITCH) in the outer SELECT
  │
  ▼ (7) Execute on DuckDB
  │  parameterised query (no string interpolation of values)
  │  timeout enforcement
  │  result → columnar arrays
  │
  ▼ (8) Post-process
  │  blank-row removal (drop rows where every measure is NULL)
  │  compute totals row (re-evaluate non-additive measures)
  │  apply FORMAT strings (client-side, or in post-process for API)
  │  build DSR response
  │
  ▼
DataShapeResult JSON → visual runtime
```

---

## 4. Step 1: Parse and bind

### 4.1 What "bind" means

The semantic query uses string names: `"table": "Directorate"`, `"measure":
"Trips"`. The binder resolves these to internal references:

```python
@dataclass
class BoundColumn:
    table: TableMeta       # resolved table metadata
    column: ColumnMeta     # resolved column metadata (name, type, is_hidden)
    source: str            # "model" | "calculated"

@dataclass
class BoundMeasure:
    name: str
    ast: DaxAst            # parsed DAX-lite AST from the measure definition
    home_table: TableMeta  # the fact table this measure aggregates
    return_type: DaxType   # integer, decimal, string, date, boolean
```

### 4.2 Binding errors

| Input | Error |
|---|---|
| `"table": "Tripp"` | `Table 'Tripp' not found. Did you mean 'Trip'?` (Levenshtein ≤ 2) |
| `"column": "Statuss"` | `Column 'Statuss' not found in table 'Trip'. Did you mean 'Status'?` |
| `"measure": "Revenue"` (doesn't exist) | `Measure 'Revenue' not found in the model.` |
| Hidden column in select | `Column 'Trip.InternalId' is hidden and cannot be used in a query.` |
| Type mismatch in filter | `Filter on 'Date.Year' has op 'contains', but Year is type integer. Use 'eq' or 'in'.` |

### 4.3 Measure expansion

Each measure reference is replaced with its parsed AST. If a measure
references another measure, that is expanded recursively. A depth limit of 64
catches circular references (which the model editor should have caught at save
time, but the engine double-checks).

```
[Completion %]
  → DIVIDE(
      CALCULATE(COUNTROWS(Trip), Trip[Status] = "Completed"),
      COUNTROWS(Trip)
    )

[Trips LY]
  → CALCULATE([Trips], SAMEPERIODLASTYEAR('Date'[Date]))
  → CALCULATE(COUNTROWS(Trip), SAMEPERIODLASTYEAR('Date'[Date]))
```

---

## 5. Step 2: Build the filter context

Filters arrive from multiple sources, in priority order:

| Source | Example | Removable by ALL? |
|---|---|---|
| **RLS predicates** | `Directorate.DeptGuid IN (user's departments)` | No (§14) |
| **Report-level filters** | `Date[Year] = 2026` | Yes |
| **Page-level filters** | `Trip[Status] IN ("Completed", "Approved")` | Yes |
| **Visual-level filters** | `Directorate[Name] <> "HQ"` | Yes |
| **Cross-filter** | `Directorate[Name] = "Operations"` | Yes |
| **Slicer selections** | `Vehicle[Type] = "Truck"` | Yes |

All filters target a single column. The engine merges them into a
`FilterContext`:

```python
@dataclass
class FilterContext:
    filters: dict[ColumnRef, Predicate]
    security_filters: dict[ColumnRef, Predicate]  # never removable

    def replace(self, column: ColumnRef, new_pred: Predicate) -> FilterContext:
        """CALCULATE's default: replace the filter on this column."""
        new = dict(self.filters)
        new[column] = new_pred
        return FilterContext(new, self.security_filters)

    def intersect(self, column: ColumnRef, new_pred: Predicate) -> FilterContext:
        """KEEPFILTERS: AND with existing filter."""
        new = dict(self.filters)
        if column in new:
            new[column] = And(new[column], new_pred)
        else:
            new[column] = new_pred
        return FilterContext(new, self.security_filters)

    def remove(self, column: ColumnRef) -> FilterContext:
        """ALL(column): remove the filter on this column."""
        new = dict(self.filters)
        new.pop(column, None)
        return FilterContext(new, self.security_filters)

    def remove_table(self, table: str) -> FilterContext:
        """ALL(table): remove all filters on columns of this table."""
        new = {k: v for k, v in self.filters.items() if k.table != table}
        return FilterContext(new, self.security_filters)
```

### 5.1 CALCULATE resolution

When the measure expander encounters a `CALCULATE` node, it:

1. Captures the **current** filter context (before CALCULATE modifies it).
2. Evaluates each filter argument against that captured context.
3. Applies each filter argument using `replace` (default) or `intersect`
   (if wrapped in KEEPFILTERS).
4. For `ALL(T)` / `ALL(T[c])` arguments, calls `remove` / `remove_table`.
5. Attaches the **new** filter context to the inner expression.

This is the implementation of DAX-lite spec §5.2.

### 5.2 Time intelligence resolution

When the measure expander encounters a time intelligence function
(`SAMEPERIODLASTYEAR`, `DATEADD`, `TOTALYTD`, etc.) as a CALCULATE argument:

1. Reads the current date filter from the filter context.
2. Applies the date rewrite rule (DAX-lite spec §8.4).
3. Produces a new date predicate: `Date[Date] BETWEEN new_start AND new_end`.
4. This predicate **replaces** the existing date filter (standard CALCULATE
   replacement).

The result is that the inner measure sees a shifted date range, which the SQL
generator emits as a modified WHERE clause.

---

## 6. Step 3: Expand measures

After CALCULATE resolution, every measure has been flattened into an
**aggregate leaf** — a single aggregation function with a fully resolved
filter context attached to it.

### 6.1 The aggregate leaf

```python
@dataclass
class AggregateLeaf:
    id: str                        # unique within the query
    function: str                  # "SUM", "COUNT", "COUNTROWS", "AVG", etc.
    column: ColumnRef | None       # None for COUNTROWS
    expression: SqlExpr | None     # for X-functions: the per-row expression
    filter_context: FilterContext  # the filters this leaf evaluates under
    home_table: str                # the fact table to aggregate
```

### 6.2 Example: a visual cell's measures decomposed

The semantic query asks for `[Trips]`, `[Completion %]`, `[Trips LY]`, grouped
by `Directorate[Name]`, filtered by `Date[Year] = 2026`.

After measure expansion:

| Leaf | Function | Home table | Filter context |
|---|---|---|---|
| L1 | COUNTROWS | Trip | `{ Date[Year]=2026 }` |
| L2 | COUNTROWS | Trip | `{ Date[Year]=2026, Trip[Status]="Completed" }` |
| L3 | COUNTROWS | Trip | `{ Date[Year]=2025 }` (shifted by SAMEPERIODLASTYEAR) |

The scalar expressions on top:
- `[Trips]` = L1
- `[Completion %]` = DIVIDE(L2, L1) = `L2 / NULLIF(L1, 0)`
- `[Trips LY]` = L3

### 6.3 Leaf deduplication

If two measures produce the same aggregate leaf (same function, same column,
same filter context, same home table), they share one leaf. In the example
above, `[Trips]` and the denominator of `[Completion %]` both use L1.

---

## 7. Step 4: Resolve relationships and joins

### 7.1 The relationship graph

The model defines relationships as:

```jsonc
{
  "from": { "table": "Trip", "column": "DepartmentGuid" },
  "to":   { "table": "Directorate", "column": "DepartmentGuid" },
  "cardinality": "many-to-one",   // Trip is many, Directorate is one
  "active": true
}
```

The engine builds a directed graph: edges go from the many side to the one
side (fact → dimension). Filter propagation follows the reverse direction
(dimension → fact): a filter on `Directorate[Name]` propagates to `Trip`
through the JOIN.

### 7.2 Path finding

For each aggregate leaf, the engine needs JOINs from the home table to every
dimension table referenced in:
- The groupBy columns
- The filter context predicates
- The measure's expression (for `RELATED` lookups)

Algorithm:

```
function findJoinPath(homeTable, targetTable, graph):
    // BFS from homeTable to targetTable, following many→one edges
    visited = {homeTable}
    queue = [(homeTable, [])]
    while queue:
        current, path = queue.pop(0)
        for edge in graph.edgesFrom(current) where edge.active:
            next = edge.toTable
            if next == targetTable:
                return path + [edge]
            if next not in visited:
                visited.add(next)
                queue.append((next, path + [edge]))
    return ERROR("No relationship path from {homeTable} to {targetTable}")
```

### 7.3 Snowflake schemas

If the model has a snowflake shape (dimension → sub-dimension, like
`Trip → Vehicle → VehicleType`), the path finder follows the chain:

```
Trip --many→one--> Vehicle --many→one--> VehicleType
```

The SQL generator emits both JOINs:

```sql
FROM Trip t
  JOIN Vehicle v ON v.VehicleGuid = t.VehicleGuid
  JOIN VehicleType vt ON vt.TypeId = v.TypeId
```

### 7.4 Ambiguous paths

If two active relationships connect `Trip` to `Date` (e.g., `Trip.StartDate →
Date.Date` and `Trip.EndDate → Date.Date`), the path finder sees two paths and
raises an error:

```
Multiple active relationships from Trip to Date:
  1. Trip.StartDate → Date.Date
  2. Trip.EndDate → Date.Date
Deactivate one, or use USERELATIONSHIP (phase 3).
```

### 7.5 Join type

All dimension joins are **INNER JOIN** by default. This matches Power BI's
behaviour: if a fact row has a foreign key that doesn't match any dimension
row, that fact row is excluded.

Exception: when a measure uses `ALL(DimTable)` to remove filters on that
dimension, the join must still include all fact rows. The engine handles this
by removing the WHERE clause on that dimension's columns, not by changing the
JOIN type. The dimension table is still INNER JOINed (it must be, for the
groupBy), but with no filter on its columns.

If the model marks a relationship as `nullable: true` (the FK can be NULL),
the join becomes a **LEFT JOIN**, so fact rows with NULL FKs are included with
NULL dimension values.

---

## 8. Step 5: Plan sub-queries (home-table grouping)

This is the chasm-trap prevention step. If the semantic query has measures
from different fact tables, joining them directly would multiply rows.

### 8.1 The rule

> Each fact table gets its own sub-query. Sub-queries are combined with
> FULL OUTER JOIN on the groupBy columns.

### 8.2 Example

Semantic query: `[Trips]` (home: Trip), `[Service Requests]` (home:
ServiceRequest), grouped by `Directorate[Name]`.

**Wrong** (single query — chasm trap):
```sql
-- DON'T: Trip × ServiceRequest produces a cross product per Directorate
SELECT d.Name, COUNT(DISTINCT t.TripId), COUNT(DISTINCT sr.RequestId)
FROM Directorate d
  JOIN Trip t ON ...
  JOIN ServiceRequest sr ON ...
GROUP BY d.Name
```

**Correct** (separate sub-queries):
```sql
WITH
  trips AS (
    SELECT d.Name, COUNT(*) AS trips
    FROM Trip t JOIN Directorate d ON ...
    WHERE ...
    GROUP BY d.Name
  ),
  requests AS (
    SELECT d.Name, COUNT(*) AS requests
    FROM ServiceRequest sr JOIN Directorate d ON ...
    WHERE ...
    GROUP BY d.Name
  )
SELECT
  COALESCE(t.Name, r.Name) AS "Directorate[Name]",
  t.trips AS "Trips",
  r.requests AS "Service Requests"
FROM trips t
FULL OUTER JOIN requests r ON r.Name = t.Name
ORDER BY t.trips DESC;
```

### 8.3 Same fact table, different filter contexts

When two measures share the same home table but have different filter contexts
(because of CALCULATE), the planner has two strategies:

**Strategy A — FILTER clause** (preferred when the difference is a single
predicate):

```sql
SELECT d.Name,
  COUNT(*)                                          AS trips,
  COUNT(*) FILTER (WHERE t.Status = 'Completed')   AS completed_trips
FROM Trip t JOIN Directorate d ON ... JOIN Date dt ON ...
WHERE dt.Year = 2026
GROUP BY d.Name
```

DuckDB supports `aggregate FILTER (WHERE ...)`, which is standard SQL:2003.

**Strategy B — separate CTEs** (when the difference involves a date shift or
removed filters that change the JOIN structure):

```sql
WITH
  current AS (
    SELECT d.Name, COUNT(*) AS trips
    FROM Trip t JOIN ... WHERE dt.Year = 2026
    GROUP BY d.Name
  ),
  prior AS (
    SELECT d.Name, COUNT(*) AS trips_ly
    FROM Trip t JOIN ... WHERE dt.Year = 2025
    GROUP BY d.Name
  )
SELECT c.Name, c.trips, p.trips_ly
FROM current c LEFT JOIN prior p ON p.Name = c.Name
```

The planner chooses:
- **FILTER clause** when the contexts differ only by added predicates on
  columns already in the base query's WHERE.
- **Separate CTE** when the contexts differ by removed filters (ALL), shifted
  dates (time intelligence), or added joins.

### 8.4 Scalar expression layer

After sub-queries produce the aggregate leaves, scalar expressions (DIVIDE,
IF, SWITCH, arithmetic) sit in the **outer SELECT**:

```sql
SELECT
  Name AS "Directorate[Name]",
  trips AS "Trips",
  completed_trips / NULLIF(trips, 0) AS "Completion %",
  trips_ly AS "Trips LY"
FROM (sub-query or CTE join)
```

This separation keeps the sub-queries clean (pure aggregation) and the scalar
layer simple (no JOINs, no GROUP BY).

---

## 9. Step 6: Generate SQL with sqlglot

### 9.1 Why sqlglot

[sqlglot](https://github.com/tobymao/sqlglot) is a Python SQL parser and
transpiler that supports 20+ dialects. We use it for:

1. **Building SQL from an AST** — not from string concatenation. This prevents
   SQL injection and makes the output predictable.
2. **Transpiling between dialects** — the same IR can emit DuckDB SQL (Import
   mode) or T-SQL (DirectQuery to SQL Server) or PostgreSQL.
3. **Optimising** — sqlglot has an optimiser pass that can push predicates,
   simplify expressions, and eliminate dead columns.

### 9.2 IR → sqlglot mapping

| IR node | sqlglot call | Notes |
|---|---|---|
| `Scan(table)` | `exp.From(this=exp.Table(this=table))` | |
| `Join(left, right, on)` | `exp.Join(this=right, on=on, kind="INNER")` | or LEFT for nullable FKs |
| `Filter(scan, predicate)` | `.where(predicate)` | |
| `Aggregate(func, col)` | `exp.Func(this=func, expressions=[col])` | SUM, COUNT, AVG, etc. |
| `FilteredAggregate(func, col, pred)` | `exp.Filter(this=agg, expression=exp.Where(this=pred))` | DuckDB `FILTER (WHERE)` |
| `GroupBy(cols)` | `.group_by(*cols)` | |
| `OrderBy(col, dir)` | `.order_by(exp.Ordered(this=col, desc=dir=="desc"))` | |
| `Limit(n)` | `.limit(n)` | |
| `CTE(name, query)` | `exp.CTE(this=query, alias=name)` | |
| `FullOuterJoin(l, r, on)` | `exp.Join(kind="FULL OUTER", ...)` | Multi-fact combination |
| `Coalesce(a, b)` | `exp.Coalesce(this=a, expressions=[b])` | For FULL OUTER JOIN keys |

### 9.3 Parameterisation

Filter values are **never** interpolated into the SQL string. They are passed
as bind parameters:

```python
sql = "SELECT ... WHERE dt.Year = $1 AND t.Status IN ($2, $3)"
params = [2026, "Completed", "Approved"]
```

DuckDB supports positional parameters (`$1`, `$2`, …). sqlglot emits
placeholder nodes that the executor replaces with parameter markers.

### 9.4 Dialect transpilation

The same IR emits different SQL per target:

| Feature | DuckDB | T-SQL (SQL Server) | PostgreSQL |
|---|---|---|---|
| FILTER clause | `COUNT(*) FILTER (WHERE ...)` | `COUNT(CASE WHEN ... THEN 1 END)` | `COUNT(*) FILTER (WHERE ...)` |
| MEDIAN | `MEDIAN(col)` | `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY col)` | `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY col)` |
| MAKE_DATE | `MAKE_DATE(y, m, d)` | `DATEFROMPARTS(y, m, d)` | `MAKE_DATE(y, m, d)` |
| LAST_DAY | `LAST_DAY(date)` | `EOMONTH(date)` | `(date_trunc('month', date) + interval '1 month' - interval '1 day')::date` |
| GROUPING SETS | Native | Native | Native |
| FULL OUTER JOIN | Native | Native | Native |
| TRY (error handling) | `TRY(expr)` | `TRY_CAST(...)`, `TRY_CONVERT(...)` | Not native — wrap in CASE |

sqlglot's `transpile(read="duckdb", write="tsql")` handles most of this
automatically. We add custom rules for the gaps.

### 9.5 SQL output for debugging

The engine exposes a `"returnSql": true` option on the semantic query. When
set, the response includes the generated SQL alongside the data. This powers
the "Compiles to" panel in the formula editor and the performance analyser in
the report viewer.

---

## 10. Step 7: Execute on DuckDB

### 10.1 Import mode (the normal path)

In Import mode, the dataset's data lives in a **DuckDB file** on disk. The
engine opens a read-only connection to this file and executes the parameterised
SQL.

```python
import duckdb

def execute_query(dataset_path: str, sql: str, params: list) -> list[dict]:
    con = duckdb.connect(dataset_path, read_only=True)
    try:
        result = con.execute(sql, params)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        con.close()
```

### 10.2 Connection pooling

Opening a DuckDB file is fast (~1ms), but the engine still pools connections
per dataset to avoid repeated file opens under concurrent requests:

```python
class ConnectionPool:
    """Per-dataset read-only connection pool."""
    pools: dict[str, queue.Queue[duckdb.DuckDBPyConnection]]

    def acquire(self, dataset_path: str) -> duckdb.DuckDBPyConnection:
        pool = self.pools.setdefault(dataset_path, queue.Queue(maxsize=8))
        try:
            return pool.get_nowait()
        except queue.Empty:
            return duckdb.connect(dataset_path, read_only=True)

    def release(self, dataset_path: str, con: duckdb.DuckDBPyConnection):
        pool = self.pools[dataset_path]
        try:
            pool.put_nowait(con)
        except queue.Full:
            con.close()
```

### 10.3 Memory limits

Each query executes with a DuckDB memory limit to prevent a single expensive
query from consuming all server RAM:

```python
con.execute(f"SET memory_limit = '{per_query_limit_mb}MB'")
con.execute(f"SET threads = {max_threads_per_query}")
```

Defaults: 512 MB per query, 4 threads. Configurable per deployment.

### 10.4 Timeout

The engine enforces a query timeout (default: 30 seconds). DuckDB doesn't
have a built-in timeout, so the engine runs the query in a thread and
cancels it via `con.interrupt()` if it exceeds the limit:

```python
import threading

def execute_with_timeout(con, sql, params, timeout_seconds=30):
    result = [None]
    error = [None]

    def run():
        try:
            result[0] = con.execute(sql, params).fetchall()
        except Exception as e:
            error[0] = e

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        con.interrupt()
        thread.join()
        raise QueryTimeoutError(f"Query exceeded {timeout_seconds}s limit")

    if error[0]:
        raise error[0]
    return result[0]
```

---

## 11. Step 8: Post-process

### 11.1 Blank-row removal

After the query returns, rows where **every measure column is NULL** are
dropped. This is the DAX-lite spec §11 rule.

```python
def remove_blank_rows(rows, measure_columns):
    return [
        row for row in rows
        if not all(row[col] is None for col in measure_columns)
    ]
```

Why post-process instead of SQL? The blank-row check must apply **after** all
sub-queries are joined. With FULL OUTER JOINs, a row might have non-NULL
values from one sub-query and NULLs from another. The post-process step sees
the final combined row and decides correctly.

Alternatively, the SQL generator can add a `WHERE NOT (m1 IS NULL AND m2 IS
NULL AND ...)` clause to the outer query. Both approaches are correct; the
post-process approach is simpler to implement and debug.

### 11.2 Totals computation

If `includeTotals: true`:

**Additive measures** (SUM, COUNT, COUNTROWS): the engine uses `GROUPING SETS`
in the SQL to compute the total in the same query:

```sql
SELECT d.Name, COUNT(*) AS trips
FROM Trip t JOIN Directorate d ON ...
GROUP BY GROUPING SETS ((d.Name), ())
```

The `()` set is the grand total row. The engine identifies it by the NULL value
in the groupBy column (or by `GROUPING(d.Name) = 1`).

**Non-additive measures** (DIVIDE, AVERAGE, DISTINCTCOUNT, any expression
built from multiple aggregates): the engine issues a **separate query** with
the groupBy columns removed. This re-evaluates the measure at the coarser
grain, producing the correct total (DAX-lite spec §12).

```python
if measure.is_additive:
    # Already computed via GROUPING SETS
    pass
else:
    # Issue a second query without the groupBy columns
    totals_query = original_query.remove_group_by()
    totals_row = execute(totals_query)
```

### 11.3 Subtotals (matrix visuals)

For matrix visuals with nested row grouping (e.g., Region > Directorate),
subtotals are one grouping set per level:

```sql
GROUP BY GROUPING SETS (
    (Region, Name),  -- detail rows
    (Region),        -- subtotal per Region
    ()               -- grand total
)
```

Non-additive measures at subtotal levels follow the same separate-query
pattern.

### 11.4 Formatting

Measures have a `format` property in the model (e.g., `"#,##0"`, `"0.0%"`,
`"$#,##0.00"`). The engine applies formatting **after** computation:

- In API responses: the DSR includes both the raw value and the formatted
  string.
- In the visual runtime: formatting happens client-side using a JavaScript
  format library, so the engine returns only raw values.

The engine supports Power BI's format string syntax (a subset of .NET custom
numeric format strings) via a small parser that converts them to JavaScript
`Intl.NumberFormat` options or Python `format()` patterns.

---

## 12. The query result contract (DSR)

The engine returns a **DataShapeResult** — a columnar JSON format optimised
for the visual runtime:

```jsonc
{
  "version": 2,

  // Schema: one entry per column in the result
  "columns": [
    { "name": "Directorate[Name]", "type": "string", "role": "groupBy" },
    { "name": "Trips", "type": "integer", "role": "measure", "format": "#,##0" },
    { "name": "Completion %", "type": "decimal", "role": "measure", "format": "0.0%" }
  ],

  // Data: columnar arrays (same length, aligned by index)
  "data": {
    "Directorate[Name]": ["Operations", "Logistics", "Finance", "HR"],
    "Trips":             [412, 301, 189, 156],
    "Completion %":      [0.93, 0.88, 0.91, 0.85]
  },

  // Totals row (if requested)
  "totals": {
    "Trips": 1058,
    "Completion %": 0.895
  },

  // Metadata
  "rowCount": 4,
  "truncated": false,          // true if limit was applied
  "queryDurationMs": 12,       // end-to-end engine time
  "sql": "WITH ...",           // only if returnSql was true
  "cacheHit": false
}
```

### 12.1 Why columnar

Columnar format is ~40% smaller than row-oriented JSON for typical dashboard
data (many rows, few columns). It also maps directly to ECharts' `dataset`
format:

```javascript
// DSR → ECharts dataset
const dataset = {
  dimensions: dsr.columns.map(c => c.name),
  source: dsr.columns.map(c => dsr.data[c.name])
};
```

### 12.2 Streaming (future)

For large result sets (>10,000 rows, e.g., table visuals with scrolling),
the engine can stream results using JSON Lines (one JSON object per chunk):

```jsonc
{"type": "schema", "columns": [...]}
{"type": "data", "offset": 0, "Directorate[Name]": [...], "Trips": [...]}
{"type": "data", "offset": 1000, "Directorate[Name]": [...], "Trips": [...]}
{"type": "complete", "rowCount": 2500, "queryDurationMs": 45}
```

This allows the visual to start rendering while data is still arriving. Not
in the MVP — the MVP returns the full result in one response.

---

## 13. Caching

### 13.1 Cache key

Every semantic query produces a deterministic cache key:

```python
def cache_key(query: SemanticQuery, user_id: str, dataset_version: str) -> str:
    # Include user_id because RLS filters differ per user
    # Include dataset_version to invalidate on data refresh
    canonical = json.dumps({
        "select": sorted(query.select, key=lambda s: s["alias"]),
        "filters": sorted(query.filters, key=lambda f: f"{f['table']}.{f['column']}"),
        "orderBy": query.orderBy,
        "limit": query.limit,
        "includeTotals": query.includeTotals,
        "userId": user_id,
        "datasetVersion": dataset_version,
    }, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()
```

### 13.2 Cache layers

| Layer | TTL | Storage | Invalidation |
|---|---|---|---|
| **In-process** (LRU) | 60 seconds | Python dict | Time-based |
| **Redis** (shared) | 5 minutes | Redis | Dataset refresh clears all keys for that dataset |

### 13.3 Cache invalidation

When a dataset refreshes (new DuckDB file swapped in), the engine increments
the dataset's `version` counter. Since the version is part of the cache key,
all existing cache entries become stale naturally — no explicit invalidation
needed.

Additionally, the engine publishes a `dataset.refreshed` event. Any cache
layer can subscribe and proactively evict entries for that dataset.

### 13.4 Cache bypass

The semantic query supports a `"noCache": true` flag for debugging and for the
"Compiles to" panel (which always wants fresh SQL).

---

## 14. Security: RLS injection

### 14.1 How RLS works

Row-Level Security is defined in the dataset model as roles with filter
predicates:

```jsonc
{
  "name": "DepartmentAccess",
  "tables": [
    {
      "table": "Directorate",
      "filter": "Directorate[DepartmentGuid] IN @userDepartments"
    }
  ]
}
```

When a user views a report, the server resolves their RLS role memberships and
replaces `@userDepartments` with their actual department GUIDs.

### 14.2 Injection into the engine

The RLS predicates are passed to the engine as part of the query context, not
as part of the semantic query (the visual doesn't know about RLS):

```python
@dataclass
class QueryContext:
    semantic_query: SemanticQuery
    dataset_id: str
    user_id: str
    rls_predicates: list[RlsPredicate]  # resolved by the server
```

The engine adds RLS predicates to the `security_filters` of every
`FilterContext`. These filters:
- Are applied to **every sub-query** that touches the restricted table.
- Are **never removable** by `ALL`, `ALLEXCEPT`, or `REMOVEFILTERS` in a
  DAX-lite measure.
- Propagate through relationships: an RLS filter on `Directorate` also
  restricts `Trip` (because Trip joins to Directorate).

### 14.3 Example

User belongs to departments `['dept-001', 'dept-002']`. RLS predicate:
`Directorate[DepartmentGuid] IN ('dept-001', 'dept-002')`.

The generated SQL for `[Trips]` grouped by `Directorate[Name]`:

```sql
SELECT d.Name, COUNT(*) AS trips
FROM Trip t
  JOIN Directorate d ON d.DepartmentGuid = t.DepartmentGuid
  JOIN Date dt ON dt.Date = t.StartDate
WHERE dt.Year = 2026
  AND d.DepartmentGuid IN ($1, $2)   -- RLS predicate, always present
GROUP BY d.Name
```

Even if the measure uses `CALCULATE([Trips], ALL(Directorate))`:

```sql
SELECT COUNT(*) AS trips
FROM Trip t
  JOIN Directorate d ON d.DepartmentGuid = t.DepartmentGuid
  -- No WHERE on d.Name (ALL removed it), but RLS stays:
  AND d.DepartmentGuid IN ($1, $2)
```

The `ALL(Directorate)` removed the visual's Directorate[Name] filter, but
the security predicate on DepartmentGuid is untouchable.

---

## 15. DirectQuery mode

In DirectQuery mode, the engine does not use DuckDB. Instead, it generates
SQL in the **source database's dialect** and executes it directly.

### 15.1 Differences from Import mode

| Aspect | Import (DuckDB) | DirectQuery |
|---|---|---|
| Data location | Local DuckDB file | Source database |
| SQL dialect | DuckDB SQL | Source dialect (T-SQL, PostgreSQL, MySQL) |
| Query speed | Fast (~10ms for simple) | Depends on source (~100ms–2s) |
| Caching | Optional (data is local) | Critical (source may be slow) |
| FILTER clause | Native | Emulated with CASE WHEN (for T-SQL) |
| Connection | Read-only file connection | Network connection pool |
| RLS | Same (predicates in WHERE) | Same |

### 15.2 Dialect selection

The dataset's connection metadata includes the source type. The engine passes
this to sqlglot:

```python
dialect = {
    "sqlserver": "tsql",
    "postgresql": "postgres",
    "mysql": "mysql",
    "duckdb": "duckdb",
}[connection.source_type]

sql = ir_to_sql(ir, dialect=dialect)
```

### 15.3 Connection management

DirectQuery uses a connection pool per source database:

```python
# SQLAlchemy for connection pooling and dialect abstraction
from sqlalchemy import create_engine

engines: dict[str, Engine] = {}

def get_engine(connection: ConnectionMeta) -> Engine:
    key = connection.id
    if key not in engines:
        engines[key] = create_engine(
            connection.connection_string,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=3600,
        )
    return engines[key]
```

### 15.4 Feature gates

Some features work differently or not at all in DirectQuery:

| Feature | Import | DirectQuery |
|---|---|---|
| MEDIAN | DuckDB native | May not be available; falls back to approximate |
| GROUPING SETS | Native | Supported in SQL Server, PostgreSQL; not in MySQL 5.x |
| FILTER clause | Native | Emulated with CASE |
| Timeout | Thread-based cancellation | Database-level query timeout |
| Large result sets | Fast (local I/O) | Slower (network transfer) |

The engine checks the source's capabilities at connection time and adjusts
the SQL generator accordingly.

---

## 16. Query limits and timeouts

### 16.1 Default limits

| Limit | Default | Configurable |
|---|---|---|
| Query timeout | 30 seconds | Yes, per deployment |
| Max result rows | 30,000 | Yes, per visual type |
| Max groupBy columns | 16 | No (hard limit) |
| Max measures per query | 100 | Yes |
| Max concurrent queries per user | 10 | Yes |
| Max concurrent queries per dataset | 50 | Yes |
| Max query text size | 1 MB | No (hard limit) |
| DuckDB memory per query | 512 MB | Yes |
| DuckDB threads per query | 4 | Yes |

### 16.2 Behaviour on limit breach

| Limit | Behaviour |
|---|---|
| Timeout | Query cancelled; DSR returned with `"error": "timeout"` |
| Max rows | Result truncated; DSR has `"truncated": true` |
| Max concurrent (user) | Query queued; if queue full, `429 Too Many Requests` |
| Max concurrent (dataset) | Query queued; if queue full, `429` |
| Memory | DuckDB raises `OutOfMemoryException`; engine returns error |

---

## 17. Observability

### 17.1 Query log

Every query execution is logged:

```jsonc
{
  "queryId": "q-2026-10-29-abc123",
  "timestamp": "2026-10-29T14:32:01Z",
  "userId": "user-42",
  "datasetId": "ds-transport",
  "reportId": "rpt-fleet",
  "visualId": "viz-bar-01",
  "measures": ["Trips", "Completion %"],
  "groupBy": ["Directorate[Name]"],
  "filterCount": 3,
  "durationMs": 12,
  "rowCount": 8,
  "cacheHit": false,
  "sql": "WITH trips AS (...) SELECT ...",
  "sqlLength": 342,
  "subQueryCount": 1,
  "leafCount": 3,
  "error": null
}
```

### 17.2 Metrics (Prometheus)

| Metric | Type | Labels |
|---|---|---|
| `query_duration_seconds` | Histogram | dataset, mode (import/direct), cache_hit |
| `query_rows_returned` | Histogram | dataset |
| `query_errors_total` | Counter | dataset, error_type |
| `query_cache_hit_ratio` | Gauge | dataset |
| `active_queries` | Gauge | dataset |
| `connection_pool_size` | Gauge | dataset |

### 17.3 Performance analyser (UI)

The report viewer includes a "Performance" panel (similar to Power BI's
Performance Analyzer) that shows:

- Each visual's query time (bar chart)
- The generated SQL (expandable)
- Cache hit/miss
- Row count
- Sub-query breakdown

This is powered by the `returnSql: true` and query log metadata. The
developer clicks "Start recording", interacts with the report, and then
reviews the recorded queries.

### 17.4 Slow query detection

Queries exceeding a configurable threshold (default: 5 seconds) are logged
at WARN level with their full SQL and the semantic query. The admin dashboard
shows a "Slow queries" view sorted by duration.

---

## 18. Worked examples

### 18.1 Simple bar chart

**Visual:** Bar chart of Trips by Directorate, filtered to 2026.

**Semantic query:**
```json
{
  "version": 2,
  "select": [
    { "type": "column", "table": "Directorate", "column": "Name" },
    { "type": "measure", "measure": "Trips" }
  ],
  "filters": [
    { "table": "Date", "column": "Year", "op": "eq", "value": 2026 }
  ],
  "orderBy": [{ "field": "Trips", "direction": "desc" }],
  "includeTotals": true
}
```

**Measure:** `Trips = COUNTROWS(Trip)`

**Pipeline trace:**

1. **Bind:** Directorate.Name → string, Trips → COUNTROWS(Trip), home = Trip.
2. **Filter context:** `{ Date[Year] = 2026 }`.
3. **Expand:** One leaf: L1 = COUNTROWS(Trip) under `{ Date[Year] = 2026 }`.
4. **Joins:** Trip → Date (on StartDate), Trip → Directorate (on DeptGuid).
5. **Plan:** One sub-query (single fact table).
6. **SQL:**

```sql
SELECT d.Name AS "Directorate[Name]",
       COUNT(*) AS "Trips"
FROM Trip t
  JOIN Directorate d ON d.DepartmentGuid = t.DepartmentGuid
  JOIN Date dt ON dt.Date = t.StartDate
WHERE dt.Year = $1
GROUP BY GROUPING SETS ((d.Name), ())
ORDER BY "Trips" DESC
-- params: [2026]
```

7. **Execute:** 12ms, 8 rows + 1 total.
8. **Post-process:** No blank rows. Total row identified by `GROUPING(d.Name) = 1`.

**DSR:**
```json
{
  "columns": [
    { "name": "Directorate[Name]", "type": "string", "role": "groupBy" },
    { "name": "Trips", "type": "integer", "role": "measure", "format": "#,##0" }
  ],
  "data": {
    "Directorate[Name]": ["Operations", "Logistics", "Finance", "HR", "Admin", "IT", "Legal", "Procurement"],
    "Trips": [412, 301, 189, 156, 134, 98, 67, 45]
  },
  "totals": { "Trips": 1402 },
  "rowCount": 8,
  "queryDurationMs": 12
}
```

### 18.2 Prior-year comparison with CALCULATE

**Measures:**
```dax
Trips = COUNTROWS(Trip)
Trips LY = CALCULATE([Trips], SAMEPERIODLASTYEAR('Date'[Date]))
YoY Change = [Trips] - [Trips LY]
YoY % = DIVIDE([YoY Change], [Trips LY])
```

**Semantic query:** Same groupBy, same filter (Year = 2026), four measures.

**Pipeline trace:**

1. **Expand:**
   - `[Trips]` → L1: COUNTROWS(Trip), context `{ Year=2026 }`
   - `[Trips LY]` → CALCULATE → shift date → L2: COUNTROWS(Trip), context `{ Year=2025 }`
   - `[YoY Change]` → L1 - L2 (scalar)
   - `[YoY %]` → (L1 - L2) / NULLIF(L2, 0) (scalar)

2. **Plan:** Same home table (Trip), but L1 and L2 have different date contexts.
   The year filter changes the WHERE clause. Strategy B: separate CTEs.

3. **SQL:**

```sql
WITH
  current_year AS (
    SELECT d.Name, COUNT(*) AS trips
    FROM Trip t
      JOIN Directorate d ON d.DepartmentGuid = t.DepartmentGuid
      JOIN Date dt ON dt.Date = t.StartDate
    WHERE dt.Year = $1
    GROUP BY d.Name
  ),
  prior_year AS (
    SELECT d.Name, COUNT(*) AS trips_ly
    FROM Trip t
      JOIN Directorate d ON d.DepartmentGuid = t.DepartmentGuid
      JOIN Date dt ON dt.Date = t.StartDate
    WHERE dt.Year = $2
    GROUP BY d.Name
  )
SELECT
  COALESCE(c.Name, p.Name) AS "Directorate[Name]",
  c.trips AS "Trips",
  p.trips_ly AS "Trips LY",
  c.trips - p.trips_ly AS "YoY Change",
  (c.trips - p.trips_ly) / NULLIF(p.trips_ly, 0) AS "YoY %"
FROM current_year c
FULL OUTER JOIN prior_year p ON p.Name = c.Name
ORDER BY c.trips DESC
-- params: [2026, 2025]
```

### 18.3 Share of total with ALL

**Measures:**
```dax
Trips = COUNTROWS(Trip)
Share of Total = DIVIDE([Trips], CALCULATE([Trips], ALL(Directorate[Name])))
```

**Pipeline trace:**

1. **Expand:**
   - `[Trips]` → L1: COUNTROWS(Trip), context `{ Year=2026 }`
   - Denominator of Share: CALCULATE removes filter on Directorate[Name]
     → L2: COUNTROWS(Trip), context `{ Year=2026 }` (Name filter removed)
   - `[Share of Total]` = L1 / NULLIF(L2, 0)

2. **Plan:** L1 and L2 share the home table. L2 has a removed filter, not an
   added one, so it's a different GROUP BY (no d.Name in the denominator).
   Strategy B: CTE for L2 (it's a scalar, no grouping).

3. **SQL:**

```sql
WITH
  detail AS (
    SELECT d.Name, COUNT(*) AS trips
    FROM Trip t
      JOIN Directorate d ON d.DepartmentGuid = t.DepartmentGuid
      JOIN Date dt ON dt.Date = t.StartDate
    WHERE dt.Year = $1
    GROUP BY d.Name
  ),
  grand_total AS (
    SELECT COUNT(*) AS total_trips
    FROM Trip t
      JOIN Date dt ON dt.Date = t.StartDate
    WHERE dt.Year = $1
  )
SELECT
  detail.Name AS "Directorate[Name]",
  detail.trips AS "Trips",
  detail.trips / NULLIF(gt.total_trips, 0) AS "Share of Total"
FROM detail
CROSS JOIN grand_total gt
ORDER BY detail.trips DESC
-- params: [2026]
```

### 18.4 Multi-fact (Trip + ServiceRequest)

**Measures:**
```dax
Trips = COUNTROWS(Trip)
Requests = COUNTROWS(ServiceRequest)
```

**Pipeline trace:**

1. **Plan:** Two home tables → two sub-queries, FULL OUTER JOIN.

2. **SQL:**

```sql
WITH
  trips AS (
    SELECT d.Name, COUNT(*) AS trips
    FROM Trip t
      JOIN Directorate d ON d.DepartmentGuid = t.DepartmentGuid
      JOIN Date dt ON dt.Date = t.StartDate
    WHERE dt.Year = $1
    GROUP BY d.Name
  ),
  requests AS (
    SELECT d.Name, COUNT(*) AS requests
    FROM ServiceRequest sr
      JOIN Directorate d ON d.DepartmentGuid = sr.DepartmentGuid
      JOIN Date dt ON dt.Date = sr.RequestDate
    WHERE dt.Year = $1
    GROUP BY d.Name
  )
SELECT
  COALESCE(t.Name, r.Name) AS "Directorate[Name]",
  t.trips AS "Trips",
  r.requests AS "Requests"
FROM trips t
FULL OUTER JOIN requests r ON r.Name = t.Name
ORDER BY t.trips DESC
-- params: [2026]
```

---

## Summary: what this spec pins down

| Question | Answer |
|---|---|
| What does a visual send? | §2 — a SemanticQuery JSON with select, filters, orderBy, limit |
| How does a measure become SQL? | §3–9 — parse → bind → filter context → expand → plan → sqlglot → execute |
| How are joins resolved? | §7 — BFS on the relationship graph, many→one edges |
| How are multi-fact queries safe? | §8 — separate sub-queries per home table, FULL OUTER JOIN |
| How does CALCULATE modify the SQL? | §5–6 — filter replacement on the FilterContext, then different WHERE/FILTER clauses |
| What does the result look like? | §12 — columnar DSR JSON |
| How is it cached? | §13 — LRU + Redis, keyed by query + user + dataset version |
| How does RLS work at query time? | §14 — security_filters injected into every sub-query, never removable |
| How does DirectQuery differ? | §15 — sqlglot transpiles to the source dialect, same pipeline otherwise |
| How do I debug a slow query? | §17 — query log, Prometheus metrics, Performance Analyser panel |

This spec and the DAX-lite spec together define the complete runtime. The
DAX-lite spec says what the user writes; this spec says how it executes.
