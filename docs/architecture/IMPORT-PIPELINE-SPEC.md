# Import pipeline specification

> **Implementation status (Sprint 2):** the SQL Server connector, type mapping, streaming import,
> atomic swap and refresh runner exist. Corrections to this spec: the live file is `live.duckdb` and
> the work file is `staging.duckdb` (older text says `current.duckdb` / `refreshing.duckdb` and
> has been updated); archives are `vN.duckdb` in the dataset directory; connectors are synchronous;
> there is **no Parquet step** yet (batches go Arrow to DuckDB, see section on Parquet below as a
> possible future optimisation); import is sequential per table; the API is under `/api/v1`.
> Details: `docs/features/MAGBI-002/README.md` and `docs/guides/sql-server-import.md`.

How data gets from a source database into a DuckDB file that the query engine
can read. This covers connectors, the browser-based transform editor, query
folding (compiling transforms to SQL), the refresh orchestrator, incremental
refresh, schema drift detection and the atomic file swap that makes a new
version live.

| | |
|---|---|
| Written | 29 October 2026 |
| Status | Import pipeline implemented in Sprint 2. Transform preview (MAGBI-006) folds steps to DuckDB SQL on `live.duckdb` and returns the fold boundary. The recipe is not stored, and refresh does not apply it yet. |
| Depends on | [DATASET-MODEL-SPEC.md](DATASET-MODEL-SPEC.md) §11, [API-SERVICE-SPEC.md](API-SERVICE-SPEC.md) §10 |
| Reference | [Power Query folding](https://learn.microsoft.com/en-us/power-query/query-folding-basics), [sqlglot](https://github.com/tobymao/sqlglot), [DuckDB Python API](https://duckdb.org/docs/api/python/overview) |

---

## Contents

1. [Design principles](#1-design-principles)
2. [End-to-end refresh flow](#2-end-to-end-refresh-flow)
3. [Connectors](#3-connectors)
4. [The transform editor](#4-the-transform-editor)
5. [Transform steps](#5-transform-steps)
6. [Query folding](#6-query-folding)
7. [The refresh orchestrator](#7-the-refresh-orchestrator)
8. [Table import execution](#8-table-import-execution)
9. [Calculated columns](#9-calculated-columns)
10. [Atomic swap and versioning](#10-atomic-swap-and-versioning)
11. [Incremental refresh](#11-incremental-refresh)
12. [Schema drift detection](#12-schema-drift-detection)
13. [Error handling and retry](#13-error-handling-and-retry)
14. [Monitoring and alerting](#14-monitoring-and-alerting)
15. [Worked example: Transport refresh](#15-worked-example-transport-refresh)

---

## 1. Design principles

1. **SQL first.** Every transform step that can be expressed in SQL is compiled
   to SQL and pushed to the source database (query folding). The source does
   the heavy lifting; the pipeline transfers only the result rows. Steps that
   cannot be folded run in Python on the worker, row by row.

2. **DuckDB is the target, not an engine.** The pipeline writes Parquet or
   CSV into DuckDB. DuckDB is a storage format here, not a processing engine.
   The source database or the Python worker does the processing.

3. **Transforms are optional.** Most MSD tables need no transforms — they are
   imported as-is with a `SELECT *` or a view. The transform editor exists for
   the cases that do need cleaning (renaming, type casting, filtering deleted
   rows, merging columns).

4. **Atomic and observable.** A refresh either succeeds completely or fails
   completely. The live DuckDB file is never written to during a refresh; a new
   file is built and swapped in atomically. Every step logs progress.

---

## 2. End-to-end refresh flow

```
                    ┌────────────────────────────┐
                    │  Refresh trigger            │
                    │  (schedule, API, manual)     │
                    └─────────┬──────────────────┘
                              │
                    ┌─────────▼──────────────────┐
                    │  1. Read model.json          │
                    │     → list of tables         │
                    │     → transform recipes      │
                    │     → connection config       │
                    └─────────┬──────────────────┘
                              │
                    ┌─────────▼──────────────────┐
                    │  2. Resolve dependency order │
                    │     (calc columns may depend │
                    │      on other tables' data)  │
                    └─────────┬──────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
     ┌────────▼───────┐ ┌────▼──────┐ ┌──────▼────────┐
     │ 3a. Import      │ │ 3b. Import│ │ 3c. Import    │
     │    Trip          │ │    Vehicle│ │    Directorate│
     │  (parallel)      │ │           │ │               │
     └────────┬───────┘ └────┬──────┘ └──────┬────────┘
              │               │               │
              └───────────────┼───────────────┘
                              │
                    ┌─────────▼──────────────────┐
                    │  4. Import Date table        │
                    │     (or auto-generate)        │
                    └─────────┬──────────────────┘
                              │
                    ┌─────────▼──────────────────┐
                    │  5. Compute calculated cols  │
                    │     (topological order)       │
                    └─────────┬──────────────────┘
                              │
                    ┌─────────▼──────────────────┐
                    │  6. Validate                  │
                    │     (row counts, schema match,│
                    │      referential spot-check)  │
                    └─────────┬──────────────────┘
                              │
                    ┌─────────▼──────────────────┐
                    │  7. Atomic swap               │
                    │     staging.duckdb         │
                    │       → live.duckdb        │
                    └─────────┬──────────────────┘
                              │
                    ┌─────────▼──────────────────┐
                    │  8. Notify                    │
                    │     (increment version,       │
                    │      invalidate cache,        │
                    │      WebSocket event)          │
                    └────────────────────────────┘
```

---

## 3. Connectors

A connector knows how to connect to a source, list its tables and columns,
and execute a SQL query against it.

### 3.1 Connector interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class SourceColumn:
    name: str
    data_type: str          # source-native type name
    is_nullable: bool
    is_primary_key: bool

@dataclass
class SourceTable:
    schema: str
    name: str
    columns: list[SourceColumn]
    estimated_rows: int | None

class Connector(ABC):
    @abstractmethod
    def connect(self, config: dict) -> None: ...

    @abstractmethod
    def list_schemas(self) -> list[str]: ...

    @abstractmethod
    def list_tables(self, schema: str) -> list[SourceTable]: ...

    @abstractmethod
    def execute_query(self, sql: str) -> Iterator[tuple]: ...

    @abstractmethod
    def get_row_count(self, schema: str, table: str) -> int: ...

    @abstractmethod
    def get_dialect(self) -> str:
        """Returns the sqlglot dialect name for this source."""
        ...

    @abstractmethod
    def close(self) -> None: ...
```

### 3.2 Supported connectors (MVP)

| Connector | Source | Library | Dialect |
|---|---|---|---|
| **SQL Server** | Microsoft SQL Server 2016+ | `pymssql` or `pyodbc` | `tsql` |
| **PostgreSQL** | PostgreSQL 12+ | `psycopg` (v3) | `postgres` |
| **MySQL** | MySQL 8.0+ | `mysql-connector-python` | `mysql` |
| **CSV / Excel** | Local or uploaded files | `pandas` / `openpyxl` | — (no query folding) |
| **DuckDB** | Another DuckDB file | `duckdb` | `duckdb` |

### 3.3 Connection configuration

```typescript
type ConnectionConfig =
  | SqlServerConnection
  | PostgresConnection
  | MySqlConnection
  | FileConnection;

interface SqlServerConnection {
  type: "sqlServer";
  host: string;
  port?: number;               // default 1433
  database: string;
  authentication: "sql" | "serviceAccount" | "integratedSecurity";
  username?: string;
  password?: string;            // stored encrypted in PostgreSQL
  encrypt?: boolean;            // default true
  trustServerCertificate?: boolean;
  connectionTimeout?: number;   // seconds, default 30
}

interface PostgresConnection {
  type: "postgresql";
  host: string;
  port?: number;               // default 5432
  database: string;
  username: string;
  password: string;
  sslMode?: "disable" | "require" | "verify-ca" | "verify-full";
}

interface MySqlConnection {
  type: "mysql";
  host: string;
  port?: number;               // default 3306
  database: string;
  username: string;
  password: string;
  ssl?: boolean;
}

interface FileConnection {
  type: "file";
  basePath: string;            // directory containing CSV/Excel files
}
```

### 3.4 Credential storage

Connection credentials (passwords, service account keys) are stored in
PostgreSQL encrypted with AES-256-GCM. The encryption key is an environment
variable (`MAGBI_CREDENTIAL_KEY`, a urlsafe-base64 encoded 32-byte key) that
never appears in logs or API responses. Implemented in
`server/magbi/storage/credentials.py`; stored tokens look like `v1:<base64>`.

The API never returns passwords in GET responses — only `"password": "***"`.

### 3.5 Connection testing

```
POST /api/v1/workspaces/{wid}/connections/test
```

Tests the connection without saving it. Returns:

```json
{
  "success": true,
  "serverVersion": "Microsoft SQL Server 2019",
  "schemas": ["dbo", "vetsp", "vehr", "vefin"],
  "latencyMs": 45
}
```

Or on failure:

```json
{
  "success": false,
  "error": "Login failed for user 'bi_reader'.",
  "code": "AUTH_FAILED"
}
```

---

## 4. The transform editor

The transform editor is a browser-based UI for defining data cleaning and
shaping steps. It is **not** a full Power Query replacement — it covers the
20% of transforms that handle 80% of real-world needs.

### 4.1 Layout

```
┌──────────────────────────────────────────────────────┐
│  Source: MSD_ERP / vetsp.Trip                         │
├──────────────────────────────────────────────────────┤
│                                                      │
│  Steps:                        Data preview:          │
│  ┌────────────────────┐        ┌────────────────────┐│
│  │ 1. Source table     │        │ TripId | StartDate ││
│  │ 2. Filter rows      │        │ t-001  | 2026-01.. ││
│  │ 3. Rename columns   │ ──────►│ t-002  | 2026-01.. ││
│  │ 4. Change type      │        │ t-003  | 2026-01.. ││
│  │ + Add step           │        │ (100 rows preview) ││
│  └────────────────────┘        └────────────────────┘│
│                                                      │
│  ┌──────────────────────────────────────────────────┐│
│  │ Generated SQL (read-only):                        ││
│  │ SELECT TripId, StartDate AS "Start Date", ...     ││
│  │ FROM vetsp.Trip                                   ││
│  │ WHERE IsDeleted = 0                               ││
│  └──────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────┘
```

### 4.2 How it works

1. The user picks a source table from the connector's schema browser.
2. The editor shows a preview of the first 100 rows.
3. The user adds transform steps (from a dropdown menu or by right-clicking
   a column header).
4. Each step modifies the pipeline. The editor re-generates the SQL and
   re-runs the preview after each step.
5. If all steps fold to SQL, the "Generated SQL" panel shows the complete
   query. If a step breaks folding, the panel shows where the fold boundary
   is.

### 4.3 Step storage

Transform steps are stored in the dataset model as a recipe per table:

```typescript
interface TransformRecipe {
  table: string;                   // the target table name in the model
  source: TableSource;             // the source table/query
  steps: TransformStep[];          // ordered list of transform steps
}
```

Each step is a JSON object with a `type` and type-specific parameters.

---

## 5. Transform steps

### 5.1 Supported steps

| Step type | Description | Foldable? |
|---|---|---|
| `filterRows` | Keep only rows matching a condition | Yes |
| `removeRows` | Remove rows matching a condition | Yes |
| `selectColumns` | Keep only listed columns (drop the rest) | Yes |
| `removeColumns` | Drop listed columns | Yes |
| `renameColumn` | Rename a column | Yes |
| `changeType` | Cast a column to a different type | Yes |
| `addColumn` | Add a computed column (SQL expression) | Yes |
| `replaceValues` | Replace specific values in a column | Yes |
| `fillDown` | Fill NULL values with the previous non-NULL | No (Python) |
| `fillValue` | Fill NULL values with a constant | Yes |
| `splitColumn` | Split a text column by delimiter | Partial |
| `mergeColumns` | Concatenate two columns | Yes |
| `trimText` | Trim whitespace from a text column | Yes |
| `uppercase` / `lowercase` | Change case | Yes |
| `extractDate` | Extract year/month/day from a datetime | Yes |
| `sortRows` | Sort by one or more columns | Yes |
| `distinctRows` | Remove duplicate rows | Yes |
| `topN` | Keep only top N rows | Yes |
| `unpivot` | Unpivot columns to rows | No (Python) |
| `pivot` | Pivot rows to columns | No (Python) |
| `groupBy` | Aggregate rows | Yes |

### 5.2 Step definitions

```typescript
type TransformStep =
  | FilterRowsStep
  | RemoveRowsStep
  | SelectColumnsStep
  | RemoveColumnsStep
  | RenameColumnStep
  | ChangeTypeStep
  | AddColumnStep
  | ReplaceValuesStep
  | FillDownStep
  | FillValueStep
  | SplitColumnStep
  | MergeColumnsStep
  | TrimTextStep
  | CaseChangeStep
  | ExtractDateStep
  | SortRowsStep
  | DistinctRowsStep
  | TopNStep
  | UnpivotStep
  | PivotStep
  | GroupByStep;

interface FilterRowsStep {
  type: "filterRows";
  column: string;
  operator: "eq" | "neq" | "gt" | "gte" | "lt" | "lte" | "contains" | "startsWith" | "endsWith" | "isNull" | "isNotNull";
  value?: any;
}

interface RenameColumnStep {
  type: "renameColumn";
  oldName: string;
  newName: string;
}

interface ChangeTypeStep {
  type: "changeType";
  column: string;
  toType: "string" | "integer" | "decimal" | "date" | "datetime" | "boolean";
}

interface AddColumnStep {
  type: "addColumn";
  name: string;
  expression: string;       // SQL expression: "YEAR(StartDate)"
  dataType: string;
}

interface ReplaceValuesStep {
  type: "replaceValues";
  column: string;
  find: any;
  replaceWith: any;
}

interface FillValueStep {
  type: "fillValue";
  column: string;
  value: any;
}

interface SplitColumnStep {
  type: "splitColumn";
  column: string;
  delimiter: string;
  maxParts?: number;
  newColumnNames: string[];
}

interface MergeColumnsStep {
  type: "mergeColumns";
  columns: string[];
  separator: string;
  newColumnName: string;
}

interface GroupByStep {
  type: "groupBy";
  groupColumns: string[];
  aggregations: {
    column: string;
    function: "sum" | "avg" | "min" | "max" | "count" | "countDistinct";
    alias: string;
  }[];
}

interface UnpivotStep {
  type: "unpivot";
  idColumns: string[];           // columns to keep
  valueColumns: string[];        // columns to unpivot
  attributeName: string;         // new column for the original column names
  valueName: string;             // new column for the values
}

interface TopNStep {
  type: "topN";
  count: number;
  orderBy: string;
  direction: "asc" | "desc";
}
```

### 5.3 Right-click column transforms

The data preview table supports right-click on a column header to show
context-appropriate transforms:

| Column type | Menu items |
|---|---|
| Any | Rename, Remove, Change type, Fill nulls, Filter/Sort |
| String | Trim, Uppercase, Lowercase, Split, Replace values |
| Date/Datetime | Extract Year, Extract Month, Extract Day |
| Numeric | Round, Add computed column |

This is the fastest way to add transforms — no dropdown hunting.

---

## 6. Query folding

### 6.1 What it is

Query folding compiles a chain of transform steps into a single SQL query that
the source database executes. Only the result rows travel over the network.
Without folding, the pipeline would pull the entire source table and transform
it in Python — slow for large tables.

### 6.2 The fold algorithm

```python
def fold_steps(source: TableSource, steps: list[TransformStep], dialect: str) -> tuple[str, list[TransformStep]]:
    """
    Returns:
      - folded_sql: a SQL query incorporating all foldable steps
      - remaining_steps: steps that couldn't be folded (run in Python)
    """
    # Start with the base query
    query = build_base_query(source)  # e.g., SELECT * FROM vetsp.Trip

    folded = []
    remaining = []

    for step in steps:
        if remaining:
            # Once folding breaks, everything after runs in Python
            remaining.append(step)
            continue

        sql = try_fold_step(query, step, dialect)
        if sql is not None:
            query = sql
            folded.append(step)
        else:
            remaining.append(step)

    return query.sql(dialect=dialect), remaining
```

### 6.3 How each step folds

| Step | SQL compilation | Notes |
|---|---|---|
| `filterRows` | `WHERE column op value` | Added to the WHERE clause |
| `removeRows` | `WHERE NOT (column op value)` | Negated filter |
| `selectColumns` | Column list in SELECT | |
| `removeColumns` | Omit from SELECT | |
| `renameColumn` | `column AS "newName"` | |
| `changeType` | `CAST(column AS type)` | Type mapped per dialect |
| `addColumn` | `expression AS "name"` in SELECT | Expression validated by sqlglot |
| `replaceValues` | `CASE WHEN column = find THEN replaceWith ELSE column END` | |
| `fillValue` | `COALESCE(column, value)` | |
| `mergeColumns` | `col1 \|\| sep \|\| col2 AS "name"` | |
| `trimText` | `TRIM(column)` | |
| `uppercase` | `UPPER(column)` | |
| `lowercase` | `LOWER(column)` | |
| `extractDate` | `EXTRACT(part FROM column)` | Part mapped per dialect |
| `sortRows` | `ORDER BY column dir` | |
| `distinctRows` | `SELECT DISTINCT ...` | |
| `topN` | `ORDER BY col dir LIMIT n` | T-SQL: `TOP n`; Postgres/DuckDB: `LIMIT n` |
| `groupBy` | `GROUP BY ... SELECT agg(col)` | |
| `splitColumn` | Partial: `SPLIT_PART` on Postgres/DuckDB; T-SQL needs `STRING_SPLIT` | Falls back on T-SQL if > 2 parts |
| `fillDown` | Not foldable | Window function possible but fragile; Python is safer |
| `unpivot` | Not foldable | SQL UNPIVOT syntax varies too much |
| `pivot` | Not foldable | SQL PIVOT syntax varies too much |

### 6.4 The fold boundary

The editor UI shows a visual indicator — a line between the last folded step
and the first Python step:

```
Steps:
  1. Source table          ─┐
  2. Filter (IsDeleted=0)   │  ← SQL (runs on source DB)
  3. Rename columns         │
  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
  4. Fill down (Manager)   ─┐
  5. Unpivot               ─┘  ← Python (runs on worker)
```

Each step also shows a tooltip: "This step runs on the source database" or
"This step runs locally."

### 6.5 sqlglot for SQL generation

Each foldable step builds a sqlglot AST node:

```python
import sqlglot
from sqlglot import exp

def fold_filter_rows(query: exp.Select, step: FilterRowsStep, dialect: str) -> exp.Select:
    column = exp.Column(this=exp.to_identifier(step.column))
    value = exp.Literal.string(step.value) if isinstance(step.value, str) else exp.Literal.number(step.value)

    ops = {
        "eq": exp.EQ, "neq": exp.NEQ,
        "gt": exp.GT, "gte": exp.GTE,
        "lt": exp.LT, "lte": exp.LTE,
        "isNull": lambda: exp.Is(this=column, expression=exp.Null()),
        "isNotNull": lambda: exp.Not(this=exp.Is(this=column, expression=exp.Null())),
    }

    if step.operator in ("isNull", "isNotNull"):
        predicate = ops[step.operator]()
    elif step.operator == "contains":
        predicate = exp.Like(this=column, expression=exp.Literal.string(f"%{step.value}%"))
    else:
        predicate = ops[step.operator](this=column, expression=value)

    return query.where(predicate)
```

The final SQL is generated by calling `query.sql(dialect=dialect)`, which
transpiles to the source's native syntax.

### 6.6 Preview execution

The data preview runs the folded SQL with `LIMIT 100` appended. If there are
remaining Python steps, the preview:
1. Executes the folded SQL with `LIMIT 1000` (to have enough rows for Python transforms).
2. Applies the Python steps in memory.
3. Returns the first 100 rows.

This means the preview is always fast, even for large source tables.

---

## 7. The refresh orchestrator

The orchestrator is a background worker process (Celery or ARQ) that runs
refresh jobs.

### 7.1 Job lifecycle

```python
@dataclass
class RefreshJob:
    id: str
    dataset_id: str
    workspace_id: str
    type: str                   # "full", "incremental", "table"
    tables: list[str] | None    # None = all tables
    status: str                 # "queued", "running", "completed", "failed", "cancelled"
    started_at: datetime | None
    completed_at: datetime | None
    progress: RefreshProgress
    error: str | None
    triggered_by: str           # "schedule", "api", "manual"
    user_id: str | None

@dataclass
class RefreshProgress:
    total_tables: int
    completed_tables: int
    current_table: str | None
    current_table_rows: int
    total_rows_imported: int
```

### 7.2 Concurrency rules

| Rule | Value | Reason |
|---|---|---|
| Max concurrent refreshes per dataset | 1 | DuckDB file is being built |
| Max concurrent refreshes per workspace | 3 | Avoid overloading source DBs |
| Max concurrent refreshes platform-wide | 10 | Worker capacity |
| Queue depth per dataset | 1 | Only the latest trigger matters |

If a refresh is already running for a dataset and a new trigger arrives, the
new trigger is queued (replacing any existing queued trigger). When the running
refresh finishes, the queued one starts.

### 7.3 Cancellation

A running refresh can be cancelled via the API. The orchestrator sets a
cancellation flag; the table importer checks this flag between tables and
aborts. The partially-built DuckDB file is deleted.

---

## 8. Table import execution

### 8.1 Per-table pipeline

For each table in the model:

```python
def import_table(
    connector: Connector,
    table: TableDefinition,
    recipe: TransformRecipe | None,
    duckdb_con: duckdb.DuckDBPyConnection,
    job: RefreshJob,
) -> int:
    # 1. Build the source query
    if recipe and recipe.steps:
        folded_sql, python_steps = fold_steps(table.source, recipe.steps, connector.get_dialect())
    else:
        folded_sql = build_select_all(table.source, connector.get_dialect())
        python_steps = []

    # 2. Execute on the source
    rows = connector.execute_query(folded_sql)

    # 3. Apply Python steps (if any)
    if python_steps:
        rows = apply_python_steps(rows, python_steps)

    # 4. Write to DuckDB
    count = write_to_duckdb(duckdb_con, table.name, rows, table.columns)

    # 5. Update progress
    job.progress.completed_tables += 1
    job.progress.total_rows_imported += count
    return count
```

### 8.2 Batched writing

For large tables, rows are written to DuckDB in batches of 10,000:

```python
def write_to_duckdb(con, table_name, rows, columns, batch_size=10_000):
    # Create the table with the correct schema
    create_sql = build_create_table(table_name, columns)
    con.execute(create_sql)

    total = 0
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            con.executemany(f"INSERT INTO {table_name} VALUES ({placeholders})", batch)
            total += len(batch)
            batch = []

    if batch:
        con.executemany(f"INSERT INTO {table_name} VALUES ({placeholders})", batch)
        total += len(batch)

    return total
```

For even better performance, the pipeline can write to Parquet first and
`COPY FROM` in DuckDB:

```python
import pyarrow as pa
import pyarrow.parquet as pq

def write_via_parquet(con, table_name, rows, columns, tmp_dir):
    # Convert to Arrow table
    arrow_table = pa.Table.from_pylist(rows, schema=build_arrow_schema(columns))

    # Write Parquet
    parquet_path = f"{tmp_dir}/{table_name}.parquet"
    pq.write_table(arrow_table, parquet_path)

    # Load into DuckDB
    con.execute(f"CREATE TABLE {table_name} AS SELECT * FROM read_parquet('{parquet_path}')")
```

The Parquet path is faster for tables > 100,000 rows because DuckDB's Parquet
reader is highly optimised.

### 8.3 Parallel table imports

Tables with no dependencies on each other are imported in parallel (using
thread pool or async tasks). The dependency order is:

1. **Independent tables** (no calculated columns that reference other tables):
   imported in parallel.
2. **Date table** (may be auto-generated from fact table date ranges):
   imported after fact tables.
3. **Calculated columns**: computed after all physical tables are loaded.

```python
import concurrent.futures

def import_all_tables(connector, model, duckdb_con, job):
    # Group 1: all physical tables (parallel)
    independent = [t for t in model.tables if not t.isDateTable or not model.dateTableConfig.autoGenerate]

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(import_table, connector, table, get_recipe(table), duckdb_con, job): table
            for table in independent
        }
        for future in concurrent.futures.as_completed(futures):
            table = futures[future]
            try:
                count = future.result()
                log.info(f"Imported {table.name}: {count} rows")
            except Exception as e:
                raise RefreshError(f"Failed to import {table.name}: {e}")

    # Group 2: auto-generate date table if configured
    if model.dateTableConfig and model.dateTableConfig.autoGenerate:
        generate_date_table(duckdb_con, model)

    # Group 3: calculated columns
    compute_calculated_columns(duckdb_con, model)
```

---

## 9. Calculated columns

Calculated columns are computed in DuckDB after all tables are loaded.

### 9.1 Dependency resolution

Calculated columns can depend on:
- Physical columns in the same table (always available after import).
- `RELATED()` lookups from dimension tables (require joins → those tables must
  be loaded first).
- Other calculated columns in the same table.

The pipeline resolves dependencies with a topological sort:

```python
def compute_calculated_columns(con, model):
    # Build dependency graph
    graph = {}
    for table in model.tables:
        for calc in table.calculatedColumns:
            deps = extract_dependencies(calc.expression)
            graph[(table.name, calc.name)] = deps

    # Topological sort
    order = topological_sort(graph)

    # Compute each in order
    for (table_name, col_name) in order:
        calc = find_calc_column(model, table_name, col_name)
        sql = compile_calc_column(calc, model)
        con.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {calc.dataType}")
        con.execute(f"UPDATE {table_name} SET {col_name} = ({sql})")
```

### 9.2 RELATED() in calculated columns

A calculated column expression like:

```dax
= RELATED(Vehicle[Weight])
```

Compiles to a correlated subquery or a JOIN-based UPDATE:

```sql
UPDATE Trip SET Weight = (
    SELECT v.Weight FROM Vehicle v WHERE v.VehicleGuid = Trip.VehicleGuid
)
```

This runs in DuckDB after both Trip and Vehicle are loaded.

---

## 10. Atomic swap and versioning

### 10.1 File layout

```
datasets/{dataset-id}/
  live.duckdb              ← live file (served to queries)
  staging.duckdb           ← being built (write-only during refresh)
  model.json                  ← current model definition
  model-history/
    v14.json
    v15.json                  ← current
  data-history/
    v14_2026-10-28T06.duckdb  ← previous data version
    v15_2026-10-29T06.duckdb  ← will be current after swap
```

### 10.2 Swap procedure

```python
import os
import shutil

def atomic_swap(dataset_path: str, version: int):
    current = f"{dataset_path}/live.duckdb"
    refreshing = f"{dataset_path}/staging.duckdb"
    history = f"{dataset_path}/data-history"
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H")

    # 1. Archive the current file
    if os.path.exists(current):
        archive_name = f"v{version - 1}_{timestamp}.duckdb"
        shutil.move(current, f"{history}/{archive_name}")

    # 2. Move the new file into place
    os.rename(refreshing, current)
    # os.rename is atomic on the same filesystem (POSIX guarantee)

    # 3. Clean up old archives (keep last 5)
    archives = sorted(os.listdir(history))
    for old in archives[:-5]:
        os.remove(f"{history}/{old}")
```

### 10.3 Zero-downtime

During the swap:
- Existing query connections that opened `live.duckdb` before the rename
  continue to read from the old file (the OS keeps the file handle open).
- New query connections after the rename open the new file.
- There is no moment when queries fail — the old file exists until all
  handles are closed, and the new file is ready before the rename.

### 10.4 Rollback

If the new data is wrong, an admin can rollback:

```
POST /api/v1/workspaces/{wid}/datasets/{did}/rollback
{ "dataVersion": 14 }
```

This copies `data-history/v14_*.duckdb` back to `live.duckdb`.

---

## 11. Incremental refresh

Full refresh reimports every row. For large fact tables (millions of rows),
this is wasteful when only recent data has changed. Incremental refresh imports
only the changed window.

### 11.1 Configuration

```typescript
interface IncrementalRefreshConfig {
  enabled: boolean;
  table: string;                   // "Trip"
  dateColumn: string;              // "StartDate"
  lookbackPeriod: {
    count: number;                 // 30
    unit: "days" | "weeks" | "months";
  };
  archivePeriod: {
    count: number;                 // 2
    unit: "months" | "years";
  };
}
```

### 11.2 How it works

Instead of replacing the entire DuckDB file, incremental refresh operates on
the existing one:

```python
def incremental_refresh(connector, config, duckdb_path, model):
    con = duckdb.connect(duckdb_path, read_only=False)

    table = config.table
    date_col = config.dateColumn
    lookback_start = compute_date(config.lookbackPeriod)
    archive_cutoff = compute_date(config.archivePeriod)

    # 1. Delete the lookback window (will be reimported with fresh data)
    con.execute(f"DELETE FROM {table} WHERE {date_col} >= ?", [lookback_start])

    # 2. Delete data older than the archive period
    con.execute(f"DELETE FROM {table} WHERE {date_col} < ?", [archive_cutoff])

    # 3. Import fresh data for the lookback window
    source_sql = f"SELECT * FROM {table.source} WHERE {date_col} >= '{lookback_start}'"
    rows = connector.execute_query(source_sql)
    write_to_duckdb(con, table, rows, model.columns)

    # 4. VACUUM to reclaim space
    con.execute("VACUUM")
    con.close()
```

### 11.3 Safety

- The lookback window overlaps with existing data, so updated rows are
  reimported correctly (delete + reinsert).
- If the refresh fails mid-way, the DuckDB file may be in a partial state.
  To handle this, incremental refresh creates a WAL checkpoint before starting
  and can recover to it on failure.
- Dimension tables are always fully refreshed (they are small).

### 11.4 Phase 3 feature

Incremental refresh is deferred to phase 3 because:
- MSD's largest table (Trip) has ~50,000 rows — full refresh takes <10 seconds.
- Getting incremental refresh right (edge cases around late-arriving data,
  schema changes, partition boundaries) is complex.
- Full refresh with atomic swap is simpler and already works.

---

## 12. Schema drift detection

When the source database schema changes between refreshes, the pipeline
detects the drift and reports it.

### 12.1 Detection algorithm

Before importing each table, the pipeline fetches the source table's current
schema and compares it to the model's expected schema:

```python
def detect_schema_drift(connector, table: TableDefinition) -> list[SchemaDrift]:
    source_columns = connector.get_columns(table.source.schema, table.source.table)
    model_columns = {c.sourceColumn or c.name: c for c in table.columns}
    drifts = []

    # Check for removed columns
    source_names = {c.name for c in source_columns}
    for model_name, model_col in model_columns.items():
        if model_name not in source_names:
            drifts.append(SchemaDrift("column_removed", table.name, model_name))

    # Check for type changes
    for source_col in source_columns:
        if source_col.name in model_columns:
            model_col = model_columns[source_col.name]
            mapped_type = map_source_type(source_col.data_type, connector.get_dialect())
            if mapped_type != model_col.dataType:
                drifts.append(SchemaDrift("type_changed", table.name, source_col.name,
                    f"{model_col.dataType} → {mapped_type}"))

    # Check for new columns
    for source_col in source_columns:
        if source_col.name not in model_columns:
            drifts.append(SchemaDrift("column_added", table.name, source_col.name))

    return drifts
```

### 12.2 Drift severity

| Drift type | Severity | Refresh behaviour |
|---|---|---|
| Column added in source | Info | Refresh proceeds; new column is ignored |
| Column removed from source | Error | Refresh fails; model must be updated |
| Column type changed | Warning | Refresh proceeds with a CAST; logged as warning |
| Table removed from source | Error | Refresh fails |
| Table added in source | Info | Not detected during refresh (only in source browser) |

### 12.3 Notification

Schema drift results are:
- Stored in the refresh job record.
- Shown in the refresh history UI.
- Sent as a WebSocket event (`dataset.schema_drift`).
- Included in failure notification emails.

---

## 13. Error handling and retry

### 13.1 Error categories

| Category | Examples | Retry? |
|---|---|---|
| **Connection** | Network timeout, auth failure, server down | Yes (up to retryCount) |
| **Schema** | Missing table/column, type mismatch | No (model must be updated) |
| **Data** | Constraint violation, overflow | No (data issue in source) |
| **Resource** | Out of disk space, out of memory | No (infrastructure issue) |
| **Timeout** | Refresh exceeds timeout limit | No (increase timeout or optimise) |
| **Cancelled** | User or API cancelled the job | No |

### 13.2 Retry logic

```python
def run_with_retry(func, max_retries, retry_delay_seconds=60):
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except ConnectionError as e:
            if attempt == max_retries:
                raise
            log.warning(f"Attempt {attempt} failed: {e}. Retrying in {retry_delay_seconds}s...")
            time.sleep(retry_delay_seconds)
            retry_delay_seconds *= 2  # exponential backoff
```

### 13.3 Partial failure

If one table fails to import, the entire refresh fails. The `staging.duckdb`
file is deleted. The `live.duckdb` remains untouched.

Rationale: partial refreshes can leave the model in an inconsistent state
(e.g., Trip rows referencing Directorate rows that weren't imported). A full
or nothing approach is safer.

---

## 14. Monitoring and alerting

### 14.1 Refresh metrics (Prometheus)

| Metric | Type | Labels |
|---|---|---|
| `refresh_duration_seconds` | Histogram | dataset, type (full/incremental), status |
| `refresh_rows_imported` | Counter | dataset, table |
| `refresh_errors_total` | Counter | dataset, error_category |
| `refresh_queue_depth` | Gauge | — |
| `refresh_active_jobs` | Gauge | — |
| `schema_drift_detected` | Counter | dataset, drift_type |

### 14.2 Alerts

| Condition | Alert | Channel |
|---|---|---|
| Refresh fails | `RefreshFailed` | Email (configured per dataset), Slack webhook |
| Refresh takes > 2x average | `RefreshSlow` | Prometheus alert → PagerDuty |
| Schema drift (error severity) | `SchemaDriftError` | Email, UI notification |
| Queue depth > 5 for > 10 minutes | `RefreshQueueBacklog` | Prometheus alert |
| Disk usage > 80% | `DiskSpaceWarning` | Infrastructure alert |

### 14.3 Refresh log

Every refresh writes a structured log:

```jsonc
{
  "jobId": "job-2026-10-29-001",
  "datasetId": "ds-transport",
  "type": "full",
  "status": "completed",
  "tables": [
    { "name": "Trip", "rows": 48500, "durationMs": 3200, "folded": true },
    { "name": "Vehicle", "rows": 312, "durationMs": 150, "folded": true },
    { "name": "Directorate", "rows": 45, "durationMs": 80, "folded": true },
    { "name": "Date", "rows": 1096, "durationMs": 50, "autoGenerated": true }
  ],
  "calculatedColumns": 0,
  "totalRows": 49953,
  "totalDurationMs": 4200,
  "duckdbFileSize": "12.4 MB",
  "schemaDrifts": [],
  "error": null
}
```

---

## 15. Worked example: Transport refresh

### 15.1 Setup

- Dataset: Transport (4 tables, 3 relationships, 5 measures)
- Connection: SQL Server `msd-db-01`, database `MSD_ERP`
- Schedule: daily at 06:00 EAT
- Transform: Trip table has a `filterRows` step: `IsDeleted = 0`

### 15.2 Execution trace

```
06:00:00  Refresh triggered (schedule)
06:00:00  Job job-2026-10-29-001 created, status: queued
06:00:01  Job started, status: running
06:00:01  Reading model.json (version 15, 4 tables)
06:00:01  Resolving dependency order: [Trip, Vehicle, Directorate] → [Date]
06:00:01  Connecting to msd-db-01:1433 / MSD_ERP

06:00:02  Importing Trip (parallel batch 1/3)
          Transform recipe: 1 step (filterRows: IsDeleted = 0)
          Folded SQL: SELECT TripId, TripNumber, StartDate, EndDate,
                      DepartmentGuid, VehicleGuid, DistanceKm, FuelLitres,
                      Status, TripType
                      FROM vetsp.Trip WHERE IsDeleted = 0
          Source query: 3.1s, 48,500 rows
          Write to DuckDB: 0.1s (via Parquet)

06:00:02  Importing Vehicle (parallel batch 2/3)
          No transform recipe
          SQL: SELECT * FROM vetsp.Vehicle
          Source query: 0.1s, 312 rows
          Write to DuckDB: <0.01s

06:00:02  Importing Directorate (parallel batch 3/3)
          No transform recipe
          SQL: SELECT * FROM vehr.Department
          Source query: 0.05s, 45 rows
          Write to DuckDB: <0.01s

06:00:05  All parallel imports complete
06:00:05  Auto-generating Date table
          Date range: 2024-01-01 to 2027-12-31 (1,461 rows)
          Generated in 0.05s

06:00:05  Computing calculated columns: 0 columns to compute

06:00:05  Validation:
          Trip: 48,500 rows ✓
          Vehicle: 312 rows ✓
          Directorate: 45 rows ✓
          Date: 1,461 rows ✓
          Referential spot-check: Trip.DepartmentGuid → Directorate: 100% match ✓
          Referential spot-check: Trip.VehicleGuid → Vehicle: 99.8% match (9 NULLs) ✓

06:00:06  Atomic swap: staging.duckdb → live.duckdb
          Archived: data-history/v14_2026-10-29T06.duckdb
          New file: 12.4 MB

06:00:06  Post-swap:
          Dataset version: 15 → 16
          Query cache invalidated (47 entries)
          WebSocket event: dataset.refreshed { datasetId: ds-transport, version: 16 }

06:00:06  Job completed. Duration: 4.2s. Rows: 50,318.
```

### 15.3 What the user sees

If a user has the Transport dashboard open at 06:00:
1. The WebSocket event fires.
2. The viewer shows a banner: "Data refreshed — click to update."
3. On click, all visuals re-query and show the latest data.

If the user is in the report designer:
1. The same WebSocket event fires.
2. All visual previews re-query automatically (no banner — the designer always
   shows live data).

---

## Summary: what this spec pins down

| Question | Answer |
|---|---|
| Where does data come from? | §3 — connectors for SQL Server, PostgreSQL, MySQL, CSV, DuckDB |
| How are transforms defined? | §4–5 — browser-based step editor; 21 step types stored as JSON recipes |
| What is query folding? | §6 — compiling transform steps to source SQL via sqlglot; fold boundary shown in UI |
| How does a refresh run? | §7–8 — orchestrator queues jobs; tables imported in parallel; batched writes to DuckDB |
| How is the new data made live? | §10 — atomic `os.rename`; zero downtime; rollback from archive |
| What about large tables? | §11 — incremental refresh (phase 3): delete lookback window + reimport |
| What if the source schema changes? | §12 — schema drift detection before import; error/warning/info severity |
| What happens on failure? | §13 — retry for connection errors; full-or-nothing for data consistency |
| How is it monitored? | §14 — Prometheus metrics, structured logs, email/Slack alerts |

This spec completes the data pipeline. Combined with the other seven specs,
the entire v2 system is now specified from source database to embedded viewer.
