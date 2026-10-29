# 03 — Transform Engine

> **Status: Planned**

---

## What It Does

Between connecting to a data source and building a model, users often need to
clean and reshape the data. The transform engine provides a Power Query-style
step editor where users can:

- Filter rows (`WHERE status = 'Active'`)
- Remove or rename columns
- Change data types
- Add calculated columns
- Split, merge, or trim text
- Pivot and unpivot tables
- Group and aggregate

Each operation is a **step** stored as JSON. Steps are composable — the output
of one step feeds the next. The user sees a preview grid showing the data after
each step, and can reorder, insert, or delete steps.

```
Source Table → Step 1 (filter) → Step 2 (rename) → Step 3 (add column) → Shaped Table
```

---

## Why This Approach

### Steps as data, not code

Each transform is stored as a JSON object:

```json
{
  "type": "filterRows",
  "column": "Status",
  "operator": "eq",
  "value": "Active"
}
```

This has three advantages over storing transforms as code (Python scripts, SQL
strings, or a custom DSL):

1. **The UI can render and edit it.** The frontend reads the JSON and shows a
   form for each step type. No parsing needed.
2. **Query folding is mechanical.** Each step type has a known SQL equivalent.
   A compiler walks the step list and produces SQL.
3. **Steps are serialisable and versionable.** The recipe travels with the
   dataset definition as plain JSON.

### Query folding: the key optimisation

**Problem:** If we run transforms in Python (load rows into a DataFrame, filter,
rename, etc.), we must first import ALL rows, then apply transforms. For a 10M
row table, this means importing 10M rows only to filter down to 100k.

**Solution: Query folding.** Instead of running transforms in Python, we
compile them into a SQL query sent to the *source* database. The source database
applies the filter, and only 100k rows travel over the network.

```
Without folding:  Source → 10M rows → Python filter → 100k rows → DuckDB
With folding:     Source → SQL WHERE → 100k rows → DuckDB
```

This is exactly what Power Query does when it shows "Query folding" indicators
in the Applied Steps pane. The difference is 100x in data transfer and memory.

### How query folding works in MagBI

The folding compiler walks the step list from first to last. For each step:

1. If the step has a SQL equivalent, it adds a clause to the growing SQL query
   (using sqlglot to build the AST).
2. If the step does NOT have a SQL equivalent (e.g., `fillDown`, which requires
   looking at previous rows), folding **stops**. All subsequent steps run in
   Python on the data returned by the folded SQL.

The point where folding stops is the **fold boundary**. The UI shows it
visually — steps above the line run in the source database; steps below run in
Python.

---

## The 21 Transform Steps

| # | Step | What it does | Folds to SQL? |
|---|------|-------------|---------------|
| 1 | filterRows | Keep rows matching a condition | Yes — `WHERE` |
| 2 | removeRows | Remove rows matching a condition | Yes — `WHERE NOT` |
| 3 | selectColumns | Keep only named columns | Yes — `SELECT` |
| 4 | removeColumns | Drop named columns | Yes — `SELECT` (all except) |
| 5 | renameColumn | Rename one column | Yes — `AS` |
| 6 | changeType | Cast a column to a different type | Yes — `CAST()` |
| 7 | addColumn | Add a computed column (expression) | Yes — `SELECT ..., expr AS name` |
| 8 | replaceValues | Replace specific values in a column | Yes — `CASE WHEN` |
| 9 | fillDown | Fill nulls with the last non-null value above | **No** — requires window |
| 10 | fillValue | Fill nulls with a constant | Yes — `COALESCE()` |
| 11 | splitColumn | Split text by delimiter into multiple columns | Partial — some DBs support it |
| 12 | mergeColumns | Concatenate columns with a separator | Yes — `CONCAT()` |
| 13 | trimText | Remove leading/trailing whitespace | Yes — `TRIM()` |
| 14 | uppercase | Convert to uppercase | Yes — `UPPER()` |
| 15 | lowercase | Convert to lowercase | Yes — `LOWER()` |
| 16 | extractDate | Extract year/month/day from a date | Yes — `EXTRACT()` |
| 17 | sortRows | Order the result | Yes — `ORDER BY` |
| 18 | distinctRows | Remove duplicate rows | Yes — `DISTINCT` |
| 19 | topN | Keep only the first N rows | Yes — `LIMIT` |
| 20 | unpivot | Turn columns into rows | Partial — DuckDB `UNPIVOT` |
| 21 | pivot | Turn rows into columns | Partial — DuckDB `PIVOT` |
| 22 | groupBy | Group and aggregate | Yes — `GROUP BY` |

**16 of 21 steps fold fully.** The remaining 5 partially fold or break folding.
This is comparable to Power Query's fold rate in practice.

---

## How Folding Works Under the Hood

The compiler starts with a base query:

```sql
SELECT * FROM source_schema.source_table
```

Each foldable step wraps this in a new SQL layer:

```python
# Step 1: filterRows (Status = 'Active')
query = sqlglot.select("*").from_(query.subquery()).where("Status = 'Active'")

# Step 2: renameColumn (OldName → NewName)
# Rewrite the SELECT list to alias OldName as NewName

# Step 3: addColumn (Total = Qty * Price)
# Add "Qty * Price AS Total" to the SELECT list
```

The result is a nested SQL query:

```sql
SELECT *, Qty * Price AS Total
FROM (
  SELECT *, OldName AS NewName
  FROM (
    SELECT * FROM source_schema.source_table
    WHERE Status = 'Active'
  )
)
```

Most databases optimise nested subqueries into a single scan, so the nesting
does not hurt performance.

When a non-foldable step is reached (e.g., `fillDown`), the compiler:
1. Finalises the SQL query up to this point
2. Executes it against the source database
3. Streams the result into Python
4. Applies the remaining steps as Python operations

---

## Key Concepts

### What is query folding? (Deeper dive)

Query folding is a specific case of **computation pushdown** — moving
computation closer to the data rather than moving data to the computation.
This principle appears everywhere in data systems:

- **Predicate pushdown** in query optimisers (push WHERE clauses into table scans)
- **Projection pushdown** (read only the columns you need)
- **Partition pruning** (skip files that cannot match the filter)
- **GPU computing** (move computation to where the data bandwidth is highest)

The insight is always the same: moving data is expensive; moving instructions is
cheap. MagBI's query folding sends instructions (SQL) to the data (source DB)
instead of moving all the data to MagBI.

### The transform recipe as a program

The step list is essentially a program written in a visual language:

```
LET source = READ "sales_orders"
LET step1 = FILTER source WHERE Status = 'Active'
LET step2 = RENAME step1.OldName TO NewName
LET step3 = ADD_COLUMN step2.Total = Qty * Price
RETURN step3
```

This is the same idea as Power Query's M language, but stored as JSON instead
of a textual DSL. The advantage is that we do not need a parser — the frontend
produces and consumes JSON directly. The disadvantage is that advanced users
cannot type formulas (they use the UI instead).

### Idempotent transforms

Every step must be idempotent — running it twice produces the same result as
running it once. This matters because the user might re-run the transform
recipe during a refresh, or the system might retry after a failure. Steps like
`filterRows` and `renameColumn` are naturally idempotent. Steps like
`addColumn` must check if the column already exists.

---

## The Preview Grid

When the user builds transforms, they see a live preview of the data after
each step. This is critical for usability — without it, users cannot tell if
their transform did what they intended.

**How it works:**
1. User adds or edits a step
2. The frontend sends the step list to the server
3. The server compiles and executes the steps, but with `LIMIT 200`
4. The server returns 200 rows of preview data
5. The frontend shows them in a grid (using TanStack Table)

**The fold boundary indicator:** The preview response includes which steps were
folded and which ran in Python. The frontend shows a visual divider in the step
list — steps above the line have a "database" icon; steps below have a "Python"
icon. This teaches the user about performance: "If I move this step above the
fold boundary, my import will be faster."

---

## Strengths

- **16/21 steps fold to SQL** — most transforms add zero overhead to import
- **Visual step editor** — users never write SQL or code
- **Preview with every change** — immediate feedback loop
- **JSON recipes are portable** — export a recipe and apply it to a different table
- **sqlglot handles dialect differences** — the same step compiles to correct SQL
  for SQL Server, PostgreSQL, and MySQL

## Weaknesses & Risks

- **Folding is fragile** — one non-foldable step breaks folding for all
  subsequent steps. Power Query has the same limitation.
- **No custom expressions** — users cannot write arbitrary expressions in
  transforms (they can in DAX measures, but not in transform steps). This limits
  power users who want to do complex string manipulation.
- **Dialect edge cases** — `splitColumn` folds differently on SQL Server vs.
  PostgreSQL vs. MySQL. Each dialect needs its own implementation.
- **No undo in the transform editor** — the user can delete steps, but there is
  no Ctrl+Z history. The report designer has undo; the transform editor does not
  (yet).

---

## For Agents

1. Transform steps live in `server/magbi/transforms/steps.py` — each step is a
   Pydantic model.
2. The folding compiler is in `server/magbi/transforms/folding.py` — it walks
   the step list and builds a sqlglot AST.
3. The Python executor (for non-foldable steps) is in
   `server/magbi/transforms/executor.py`.
4. When adding a new step type:
   - Add its Pydantic model to `steps.py`
   - Add its SQL compilation to `folding.py` (if it folds)
   - Add its Python execution to `executor.py` (for when it does not fold)
   - Add it to the step table in this chapter
5. Never break the fold boundary unnecessarily. If a step CAN fold, it MUST
   fold. Do not add a Python fallback for laziness.

---

## Further Reading

- [Power Query M formula language](https://learn.microsoft.com/en-us/powerquery-m/)
- [Query Folding in Power Query](https://learn.microsoft.com/en-us/power-query/query-folding-basics)
- [Computation pushdown in Spark](https://spark.apache.org/docs/latest/sql-performance-tuning.html)
- [sqlglot: Python SQL parser and transpiler](https://sqlglot.com/)
