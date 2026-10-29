# 06 — Query Engine

> **Status: Planned**

---

## What It Does

The query engine is the core runtime of MagBI. Every time a chart renders, a
table loads, or a card displays a number, the frontend sends a **Semantic
Query** to the engine, and the engine returns a **DataShapeResult** (DSR) — a
columnar JSON blob with the answer.

The engine's job is to translate "what the user wants to see" (expressed as
fields and filters) into SQL, execute it against DuckDB, and return the result
in a format the frontend can render.

```
Frontend → SemanticQuery JSON → Query Engine → SQL → DuckDB → DSR JSON → Visual
```

A typical dashboard with 12 visuals fires 12 semantic queries when the page
loads. When the user clicks a bar (cross-filter), only the affected visuals
re-query — typically 11 queries. The engine must handle this concurrency
efficiently.

---

## Why This Approach

### Semantic queries, not raw SQL

The frontend never writes SQL. Instead, it sends a structured JSON object
describing what it needs:

```json
{
  "from": [{ "table": "Sales" }],
  "select": [
    { "column": { "table": "Product", "column": "Category" } },
    { "measure": { "table": "Sales", "measure": "Revenue" } }
  ],
  "where": [
    { "column": { "table": "Date", "column": "Year" },
      "operator": "eq", "values": [2026] }
  ],
  "orderBy": [{ "select": 1, "direction": "desc" }]
}
```

**Why this matters:**

1. **Security.** The frontend cannot inject arbitrary SQL. The engine controls
   every SQL statement that runs.
2. **Abstraction.** The frontend does not know about joins, subqueries, or
   dialect differences. It asks for "Category and Revenue where Year=2026" and
   the engine figures out the rest.
3. **Optimisation.** The engine can cache, batch, and optimise queries because
   it understands their structure. Raw SQL is opaque.
4. **RLS enforcement.** The engine injects security filters that the frontend
   cannot bypass.

### An 8-step pipeline

Rather than a monolithic function that does everything, the engine is a
pipeline of eight discrete stages. Each stage has a clear input and output,
can be tested independently, and can be optimised separately.

**Why pipelines:** Compilers, query engines, and data processors all use
pipelines because they decompose a complex transformation into manageable
steps. Each step transforms a well-defined data structure into another. If a
bug appears, you can inspect the intermediate state between any two stages.

---

## How It Works — The 8-Step Pipeline

### Step 1: Parse

Read the SemanticQuery JSON and validate its shape. Check that required fields
exist, types are correct, and values are within bounds.

**Input:** Raw JSON from the HTTP request
**Output:** A typed `SemanticQuery` object (Pydantic model)

### Step 2: Bind

Resolve all table, column, and measure names against the semantic model. Verify
that `Product[Category]` actually exists, that `Sales[Revenue]` is a real
measure, and that `Date[Year]` is the right data type for the filter.

**Input:** `SemanticQuery` + `DatasetDefinition` (the model)
**Output:** `BoundQuery` — every reference is resolved to a model object

If binding fails (unknown table, unknown column), the engine returns a clear
error: "Column 'Categry' not found in table 'Product'. Did you mean 'Category'?"

### Step 3: Build filter context

Combine all active filters into a single FilterContext object:

```
FilterContext = user_filters + cross_filters + report_filters + page_filters
              + visual_filters + RLS_filters
```

**Filter precedence:** Filters combine with AND — all must be true for a row
to be included. When two filters target the same column, the behaviour depends
on how they arrived:

| Source | Behaviour |
|--------|-----------|
| Same-column user filters | Intersect (AND) |
| CALCULATE filter argument | Replace (overwrite existing filter on that column) |
| KEEPFILTERS argument | Intersect (AND with existing) |
| RLS filter | Always AND, never removable |

**The FilterContext class** tracks which filters came from which source so that
CALCULATE can correctly replace or intersect.

### Step 4: Expand measures

Each measure in the query is a DAX-lite expression. The compiler (chapter 05)
expands it into a sqlglot IR tree. If a measure references another measure
(e.g., `Profit Margin = DIVIDE([Profit], [Revenue])`), the expansion is
recursive.

**Cycle detection:** If measure A references measure B which references A, the
engine detects the cycle and returns an error. This is checked via a simple
visited-set during recursive expansion.

### Step 5: Resolve joins

The query might reference columns from multiple tables: `Product[Category]` and
`Sales[Amount]` and `Date[Year]`. The engine must determine how to join these
tables.

**The relationship graph** is built from the model's `relationships` array.
Each relationship is an edge in a directed graph:

```
Sales --[many-to-one]--> Product
Sales --[many-to-one]--> Date
Sales --[many-to-one]--> Customer
```

**BFS (Breadth-First Search)** finds the shortest join path from each referenced
table to the others. Starting from the fact table (identified as the table with
the most many-side relationships), BFS traverses relationships to reach each
dimension table.

**Why BFS, not DFS (Depth-First Search):** BFS finds the shortest path, which
minimises the number of joins. DFS might find a longer path through intermediate
tables, producing less efficient SQL. BFS is also deterministic — the same query
always produces the same join plan.

**Ambiguous paths:** If two paths exist between tables A and B (e.g., through
two different date relationships), the engine uses the **active** relationship.
If neither or both are active, it returns an error asking the user to specify
via USERELATIONSHIP.

### Step 6: Group sub-queries (chasm-trap prevention)

This is the most subtle step in the pipeline. It prevents a class of bug called
the **chasm trap**.

#### What is a chasm trap?

Consider a model with two fact tables that share a dimension:

```
Orders ──→ Customer ←── Returns
```

A query that asks for "Customer Name, Total Orders, Total Returns" must join
Customer to both Orders and Returns. If you write this as a single query:

```sql
SELECT Customer.Name,
       COUNT(Orders.ID) AS TotalOrders,
       COUNT(Returns.ID) AS TotalReturns
FROM Customer
LEFT JOIN Orders ON Orders.CustomerID = Customer.ID
LEFT JOIN Returns ON Returns.CustomerID = Customer.ID
GROUP BY Customer.Name
```

This produces **wrong results**. A customer with 3 orders and 2 returns creates
a Cartesian product of 3×2=6 rows before grouping. `COUNT(Orders.ID)` returns
6, not 3.

#### How MagBI prevents it

The engine groups measures by their **home table** (the fact table they
aggregate from). Each group becomes a separate sub-query:

```sql
-- Sub-query 1: Orders measures
SELECT Customer.Name, COUNT(Orders.ID) AS TotalOrders
FROM Customer LEFT JOIN Orders ON ...
GROUP BY Customer.Name

-- Sub-query 2: Returns measures
SELECT Customer.Name, COUNT(Returns.ID) AS TotalReturns
FROM Customer LEFT JOIN Returns ON ...
GROUP BY Customer.Name
```

Then the sub-queries are combined with FULL OUTER JOIN on the grouping columns:

```sql
SELECT COALESCE(sq1.Name, sq2.Name) AS Name,
       sq1.TotalOrders,
       sq2.TotalReturns
FROM sq1 FULL OUTER JOIN sq2 ON sq1.Name = sq2.Name
```

**Why FULL OUTER JOIN:** A customer might have orders but no returns (or vice
versa). INNER JOIN would drop them. LEFT JOIN would be asymmetric. FULL OUTER
JOIN preserves all rows from both sides.

**When a single query suffices:** If all measures come from the same fact table,
there is no chasm trap and the engine generates a single query (more efficient).
The grouping logic detects this common case and skips the FULL OUTER JOIN.

### Step 7: Generate SQL

The sqlglot IR trees from steps 4–6 are assembled into final SQL. The generator
handles:

- **Dialect:** DuckDB SQL for imported data; T-SQL or PostgreSQL for DirectQuery
- **Parameterisation:** Filter values become `$1, $2, ...` parameters, not
  inline strings. This prevents SQL injection and enables prepared-statement
  caching.
- **GROUPING SETS:** When the query requests totals/subtotals, the engine adds
  `GROUPING SETS` to the GROUP BY clause rather than running separate queries.

**Why sqlglot for generation:** Writing SQL as string concatenation is
error-prone and dialect-specific. sqlglot builds an AST, validates it, and
outputs correct SQL for any target dialect. The same IR produces:

```sql
-- DuckDB
SELECT "Category", SUM("Amount") FROM "Sales" GROUP BY "Category"

-- SQL Server
SELECT [Category], SUM([Amount]) FROM [Sales] GROUP BY [Category]

-- PostgreSQL
SELECT "Category", SUM("Amount") FROM "Sales" GROUP BY "Category"
```

### Step 8: Execute and post-process

The generated SQL runs against DuckDB (or the source database for DirectQuery).

**DuckDB execution details:**
- **Connection pool:** The engine maintains a pool of DuckDB connections. Each
  concurrent query gets its own connection. DuckDB supports concurrent readers
  on the same file.
- **Memory limit:** Each query is limited to a configurable memory budget
  (default: 1GB). DuckDB spills to disk if the budget is exceeded.
- **Timeout:** Each query has a timeout (default: 30 seconds). If exceeded, the
  query is cancelled and the engine returns an error.

**Post-processing:**
1. **Blank-row removal:** Rows where all measures are NULL are removed (auto-exist).
2. **Totals injection:** If GROUPING SETS were used, the total rows are tagged.
3. **DSR formatting:** The result is converted to DataShapeResult format.

---

## The DataShapeResult (DSR) Format

The response is a columnar JSON object:

```json
{
  "columns": [
    { "name": "Category", "dataType": "string", "isMeasure": false },
    { "name": "Revenue", "dataType": "decimal", "isMeasure": true }
  ],
  "rows": [
    ["Electronics", 45000.00],
    ["Clothing", 32000.00],
    ["Food", 18500.00]
  ],
  "rowCount": 3
}
```

**Why columnar (arrays of arrays) instead of row-oriented (array of objects):**

1. **Smaller payloads.** Column names appear once in `columns`, not repeated per
   row. For 1000 rows × 10 columns, this saves ~50% of JSON size.
2. **Type-consistent.** Each position in the inner array has a known type from
   the `columns` metadata. The frontend can parse and format without guessing.
3. **Efficient rendering.** Table and chart visuals iterate by column (to set
   axes, series, etc.), not by row. Columnar format aligns with this.

---

## Caching

The engine caches query results at two levels:

### L1: In-process LRU cache

A Python `lru_cache` (or `cachetools.LRUCache`) keyed on the hash of:
- Dataset ID
- Dataset version (incremented on refresh)
- Serialised SemanticQuery
- User's RLS role

**Why version in the key:** When a dataset is refreshed, the version increments,
automatically invalidating all cached results for the old version. No explicit
cache purge needed.

**Size:** Default 500 entries per worker process. Each entry is a DSR JSON blob,
typically 1–100KB.

### L2: Redis cache

For multi-worker deployments, a Redis cache shares results across processes.
Same key structure, with a TTL of 5 minutes.

**Why Redis, not Memcached:** Redis supports richer data structures (we use it
for pub/sub and job queues too), has persistence options, and is already in the
stack.

---

## RLS Injection

Row-Level Security filters are injected in step 3 (build filter context) and
flow through every subsequent step. The critical invariant:

> **RLS filters appear in a separate WHERE clause that no DAX function can remove.**

Implementation: the SQL generator adds RLS filters as an outer wrapper:

```sql
-- RLS wrapper (NEVER removable)
SELECT * FROM (
    -- Inner query (ALL/REMOVEFILTERS can modify this WHERE)
    SELECT Category, SUM(Amount) AS Revenue
    FROM Sales JOIN Product ON ...
    WHERE Product.Category IN ('Electronics', 'Clothing')  -- user filter
    GROUP BY Category
) sub
WHERE sub.Department = 'Finance'  -- RLS filter, immovable
```

Actually, the implementation places RLS in every sub-query's WHERE clause
(not as a wrapper), but the principle is the same: ALL and REMOVEFILTERS
operate on the inner filter list; RLS is on a separate, untouchable list.

---

## DirectQuery Mode

In DirectQuery mode, the data is NOT imported into DuckDB. Instead, the query
engine generates SQL for the source database dialect and executes it directly.

```
Standard: Semantic Query → SQL → DuckDB (imported data)
DirectQuery: Semantic Query → SQL → Source DB (live data)
```

**When to use DirectQuery:**
- The data is too large to import (billions of rows)
- Real-time data is required (stock prices, IoT sensors)
- The source database is powerful enough to handle analytical queries

**Trade-offs:**
- Slower (network latency + source DB may not be optimised for analytics)
- Source DB must handle the query load (concurrent BI users add pressure)
- Some DAX functions may not translate to the source dialect
- No caching in DuckDB (but Redis cache still works)

---

## Key Concepts

### What is a query plan?

A query plan is the series of operations the database will perform to execute a
SQL query. Understanding query plans is essential for debugging slow queries.

DuckDB's `EXPLAIN` command shows the plan:

```sql
EXPLAIN SELECT Category, SUM(Amount) FROM Sales
JOIN Product ON Sales.ProductID = Product.ID
GROUP BY Category;
```

The output shows a tree of operations: scan → join → aggregate → project. Each
node shows its estimated cost. If a query is slow, the plan reveals where time
is spent (usually in large joins or full table scans).

### What is a correlated subquery?

A correlated subquery references a column from the outer query:

```sql
SELECT p.Name,
       (SELECT SUM(s.Amount) FROM Sales s WHERE s.ProductID = p.ID) AS Revenue
FROM Product p
```

The inner SELECT runs once per row of the outer query. This is how context
transition compiles (chapter 05). DuckDB optimises many correlated subqueries
into joins, but not all — some are genuinely slow.

### What is a Cartesian product (cross join)?

When two tables are joined without a condition, every row of table A pairs with
every row of table B. For 1000 × 1000 rows, this produces 1,000,000 rows. This
is the chasm trap mechanism — an unintended Cartesian product inflates counts.

---

## Strengths

- **Correct multi-fact handling** — the chasm-trap prevention algorithm produces
  correct results where a naive single-query approach would fail
- **Dialect-portable** — the same semantic query runs on DuckDB, SQL Server, or
  PostgreSQL via sqlglot transpilation
- **Parameterised queries** — prevent SQL injection and enable prepared-statement
  caching
- **Two-level caching** — fast repeated queries (common in dashboards where
  users go back and forth)
- **RLS is unforgeable** — security filters cannot be bypassed by DAX formulas

## Weaknesses & Risks

- **Complex pipeline has many failure points** — 8 stages means 8 places where
  a bug can produce wrong results. Extensive testing is essential.
- **FULL OUTER JOIN is expensive** — for queries with 3+ fact tables, the
  FULL OUTER JOIN chain gets complex and potentially slow.
- **Correlated subqueries from context transition** — can be slow on large
  datasets; DuckDB's optimiser helps but does not eliminate all cases.
- **Cache invalidation on filter change** — a slicer change invalidates all
  cached queries for that visual. Dashboards with many slicers generate many
  cache misses.
- **DirectQuery dialect coverage** — not every DuckDB SQL feature has a
  T-SQL equivalent. Some measures may not work in DirectQuery mode.

---

## For Agents

1. The query engine lives in `server/magbi/engine/`. Each pipeline step is a
   function in its own file.
2. `pipeline.py` orchestrates the 8 steps. Do not reorder them — each step
   depends on the previous step's output.
3. The chasm-trap prevention logic is in `grouping.py`. This is the most
   delicate code. Test it with multi-fact queries.
4. RLS injection is in `filter_context.py`. If you modify filter handling,
   verify that RLS filters survive ALL and REMOVEFILTERS.
5. The DSR format is defined in `web/src/types/query.ts`. Do not change it
   without updating both server and frontend.
6. Add golden tests for new query patterns. A golden test is a (SemanticQuery,
   expected SQL, expected DSR) triple.

---

## Further Reading

- [How Power BI generates queries (SQLBI)](https://www.sqlbi.com/articles/optimizing-dax-with-query-plans/)
- [The chasm trap in data modelling](https://en.wikipedia.org/wiki/Entity%E2%80%93relationship_model#Chasm_trap)
- [DuckDB query execution internals](https://duckdb.org/docs/internals/overview)
- [GROUPING SETS, ROLLUP, CUBE in SQL](https://modern-sql.com/feature/grouping-sets)
- [BFS algorithm (Wikipedia)](https://en.wikipedia.org/wiki/Breadth-first_search)
- [LRU cache design](https://en.wikipedia.org/wiki/Cache_replacement_policies#Least_recently_used_(LRU))
