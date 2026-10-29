# 10 — Storage & Data Refresh

> **Status: Planned**

---

## What It Does

The storage and refresh layer answers two questions:

1. **Where does the analytical data live?** In DuckDB files — one file per
   dataset version, managed as plain files on the server's filesystem.
2. **How does the data get updated?** A background refresh pipeline connects
   to the source database, imports data through the connector and transform
   layers, writes it to a new DuckDB file, and swaps it in atomically so
   queries never see partial data.

### The data lifecycle

```
Source DB → Connector → Transforms → Parquet batches → DuckDB file (new)
                                                            │
                                        atomic swap (os.rename)
                                                            │
                                                    DuckDB file (live) ← Query Engine
                                                            │
                                              DuckDB file (archive, up to 5 versions)
```

---

## Why This Approach

### Why DuckDB files over a shared analytical database

The conventional approach is to load imported data into a shared analytical
database (ClickHouse, Redshift, a dedicated PostgreSQL with columnar extensions).
MagBI uses individual DuckDB files instead. Here is why:

| Concern | Shared DB | DuckDB files |
|---------|-----------|-------------|
| **Deployment** | Requires running and managing another server | No server — it is a library linked into the Python process |
| **Isolation** | Datasets share resources (memory, CPU, disk I/O) | Each dataset is an independent file — one slow query cannot starve others |
| **Refresh** | Must update rows in place (UPDATE/DELETE/INSERT) or maintain staging tables | Write a new file, swap atomically. Old version is instantly available for rollback |
| **Backup** | Database-level backup tools (pg_dump, clickhouse-backup) | Copy the file. That is the backup. |
| **Scaling** | Vertical (bigger server) or horizontal (sharding, which is complex) | Move files to different volumes or servers. No sharding logic needed. |
| **Cost** | Dedicated server runs 24/7 even when no queries are running | DuckDB uses memory only when a query is running |

**The decisive advantage: atomic swap.** When refreshing data, we write a
completely new DuckDB file. When it is ready, we rename it over the live file.
`os.rename()` is atomic on all major filesystems — the query engine never sees
a half-written file. This is the same technique that SQLite uses for WAL
checkpointing and that many databases use for SSTable compaction.

**The trade-off: single-writer limitation.** DuckDB allows only one writer at
a time. This means:
- Only one refresh job can write to a dataset's DuckDB file at a time
- We enforce this with a lock in the job orchestrator
- This is acceptable because refreshes are infrequent (hourly or daily) and
  readers are not blocked during the write (they use the live file)

### Alternatives rejected

- **ClickHouse** — Excellent analytical DB, but running a ClickHouse cluster
  adds operational complexity. For most deployments (1-50 datasets, <100M
  rows total), DuckDB files are simpler and faster.
- **PostgreSQL with pg_analytics** — Columnar extension for Postgres. Promising
  but immature. We already use Postgres for metadata; adding analytical data
  would mix OLTP and OLAP workloads.
- **Parquet files queried by DuckDB** — DuckDB can query Parquet directly. But
  Parquet lacks indexes and the first query on cold Parquet is slow. A DuckDB
  file has internal statistics and indexes that make repeated queries fast.

---

## How It Works

### DuckDB File Layout

```
data/
└── datasets/
    └── {dataset-uuid}/
        ├── live.duckdb          ← current version (symlink or rename target)
        ├── v5.duckdb            ← latest version
        ├── v4.duckdb            ← previous version
        ├── v3.duckdb            ← archive
        ├── v2.duckdb            ← archive
        └── v1.duckdb            ← oldest archive (v0 was deleted)
```

- **`live.duckdb`** is always the version the query engine reads from
- **`vN.duckdb`** files are numbered sequentially
- **5 archived versions** are kept for rollback. Older versions are deleted.
- Each `.duckdb` file is a complete, self-contained database with all tables

### The Refresh Pipeline

When a refresh is triggered (manually or by schedule), here is what happens
step by step:

```
1. TRIGGER
   User clicks "Refresh" or the scheduler fires
   → POST /api/refresh/{dataset-id}/trigger

2. ENQUEUE
   The API creates a Celery task: refresh_dataset(dataset_id)
   Task enters the queue

3. ACQUIRE LOCK
   The worker picks up the task
   Checks concurrency limits:
   - 1 concurrent refresh per dataset (prevents double-write)
   - 3 concurrent refreshes per workspace (prevents resource starvation)
   - 10 concurrent refreshes platform-wide (prevents server overload)
   If limits are hit, the task is retried after a delay

4. CREATE STAGING FILE
   Worker creates a new empty DuckDB file: vN+1.duckdb
   Opens it in write mode

5. IMPORT TABLES (parallel)
   For each table in the dataset definition:
   a. Open a connector to the source database
   b. Compile transform steps to SQL (query folding)
   c. Execute the folded SQL against the source
   d. Stream rows in batches (10,000 rows)
   e. Convert each batch to a PyArrow RecordBatch
   f. When accumulated batches reach 100MB, flush to a Parquet buffer
   g. COPY the Parquet buffer into the DuckDB staging file
   
   Tables are imported in parallel (ThreadPoolExecutor, max 4 threads)
   to overlap network I/O with disk I/O

6. CALCULATED COLUMNS
   After all tables are imported:
   a. Topological-sort calculated columns by dependency order
   b. For each calculated column:
      - Compile its DAX-lite expression to SQL
      - Execute: ALTER TABLE ADD COLUMN ... DEFAULT (expression)
      - Or: UPDATE table SET col = (expression)
   c. RELATED() expressions become correlated subqueries:
      UPDATE Orders SET CustomerName = (
        SELECT c.Name FROM Customers c
        WHERE c.CustomerID = Orders.CustomerID
      )

7. ATOMIC SWAP
   Close the staging DuckDB file
   Rename: vN+1.duckdb → live.duckdb
   (os.rename is atomic on Linux ext4/XFS and Windows NTFS)
   
   Old live.duckdb is now vN.duckdb (renamed before the swap)
   If > 5 archived versions exist, delete the oldest

8. POST-REFRESH
   Invalidate query cache for this dataset (delete Redis keys)
   Send WebSocket event: dataset.refreshed
   Update refresh history in PostgreSQL (duration, row counts, status)
   Release the concurrency lock
```

### Per-Table Import: The Details

Each table import is a pipeline:

```
Source DB
  │
  ├── Connector.read_table() — streams rows in batches
  │
  ├── Transform executor — applies non-foldable steps (if any)
  │
  ├── PyArrow conversion — rows → RecordBatch (columnar in memory)
  │
  ├── Parquet buffer — accumulates batches until 100MB threshold
  │
  └── DuckDB COPY — bulk loads the Parquet buffer into the staging file
```

**Why the Parquet intermediate step?** DuckDB's fastest bulk loading method
is `COPY FROM 'file.parquet'`. Converting row batches to Parquet and then
loading the Parquet is faster than inserting rows one-by-one or even
batch-inserting with executemany(). The Parquet buffer sits in memory (or
spills to a temp file if it exceeds the threshold) — we never write persistent
Parquet files.

### Calculated Columns and Dependency Order

Calculated columns are expressions that compute a new column from existing ones.
They can reference other calculated columns, creating dependencies:

```
TotalCost = [Quantity] * [UnitPrice]
TaxAmount = [TotalCost] * [TaxRate]
GrandTotal = [TotalCost] + [TaxAmount]
```

`GrandTotal` depends on `TotalCost` and `TaxAmount`. `TaxAmount` depends on
`TotalCost`. The correct computation order is:

```
1. TotalCost   (depends on raw columns only)
2. TaxAmount   (depends on TotalCost)
3. GrandTotal  (depends on TotalCost and TaxAmount)
```

This is a **topological sort** — a standard algorithm that orders nodes in a
directed acyclic graph (DAG) so that every node comes after its dependencies.
If there is a cycle (A depends on B, B depends on A), the sort fails and we
report a validation error.

### The RELATED() Function

In Power BI, `RELATED()` fetches a value from a related table via a
relationship. In MagBI, during refresh, `RELATED(Customers[Name])` on the
Orders table becomes:

```sql
UPDATE Orders SET CustomerName = (
  SELECT c.Name
  FROM Customers c
  WHERE c.CustomerID = Orders.CustomerID
)
```

This is a **correlated subquery** — for each row in Orders, DuckDB looks up
the matching row in Customers. DuckDB optimises this into a hash join
internally, so it is efficient even for large tables.

### Atomic Swap: Why It Matters

Without atomic swap, the refresh has a dangerous window:

```
Bad approach:
1. DELETE all rows from live tables
2. INSERT new rows
   ← If a query runs here, it sees empty tables!
3. Done
```

With atomic swap:

```
Good approach:
1. Write all data to staging file (live file untouched)
2. Rename staging → live (atomic, instant)
   ← Queries before the rename see old data
   ← Queries after the rename see new data
   ← No query ever sees partial data
```

`os.rename()` is atomic because the filesystem updates a single directory entry
(the inode pointer). It does not copy data. Even for a 10GB DuckDB file, the
rename takes microseconds.

### Incremental Refresh

For very large tables (100M+ rows), full reimport is slow. Incremental refresh
reimports only recent data:

```
Configuration:
  incrementalColumn: "ModifiedDate"
  lookbackPeriod: "P30D"   (30 days, ISO 8601 duration)

Algorithm:
  1. Compute cutoff: today - 30 days
  2. DELETE FROM table WHERE ModifiedDate >= cutoff
  3. Import only rows WHERE ModifiedDate >= cutoff from source
  4. Result: old data preserved, recent data refreshed
```

The **lookback period** handles late-arriving data — rows that were modified
in the source after the last refresh but with a ModifiedDate before the
refresh time. 30 days of lookback catches most late arrivals.

**Limitation:** Incremental refresh only works for append-like tables with a
reliable date column. Tables where old rows are updated or deleted (without
updating the date column) must use full refresh.

### Schema Drift Detection

Between refreshes, the source database schema may change:

| Change | Detection | Response |
|--------|-----------|----------|
| Column added | New column in source, not in model | Warning — column is available but not yet in the model |
| Column removed | Column in model, not in source | Error — refresh fails, model must be updated |
| Column type changed | Type mismatch between model and source | Warning — auto-cast if safe, error if lossy |
| Table removed | Table in model, not in source | Error — refresh fails |

Detection happens at the start of the import step for each table. The connector
reads the source schema and compares it to the model definition. If a breaking
change is detected, the refresh aborts before writing any data, and the live
file remains untouched.

---

## Key Concepts

### What is atomic file swap?

An atomic operation is one that either completes fully or not at all — there is
no intermediate state visible to other processes. File rename on POSIX systems
is atomic because:

1. The kernel updates a single directory entry
2. The old file's inode is unlinked
3. The new file's inode takes its place
4. Any process that had the old file open can still read it (the inode is not
   deleted until all file handles are closed)

This is a property of the filesystem, not application logic. MagBI does not
implement atomicity — it relies on the OS to provide it.

On **Windows NTFS**, `MoveFileEx` with `MOVEFILE_REPLACE_EXISTING` provides
the same atomicity guarantee.

### Concurrency control without locks on DuckDB

DuckDB's single-writer model means:
- One process writes (the refresh worker)
- Multiple processes read (the query engine instances)
- Readers do not block the writer
- The writer does not block readers

This is possible because the writer creates a *new* file while readers use the
*live* file. They never touch the same file simultaneously. After the swap,
readers who opened the old file keep reading it (the OS keeps the file alive
until all handles close), and new readers open the new file.

This is a form of **MVCC (Multi-Version Concurrency Control)** at the file
level — each version is a complete snapshot, and readers always see a consistent
snapshot.

### Why Celery for background jobs?

Celery is the standard Python task queue. It:
- Distributes tasks across multiple worker processes
- Handles retries with exponential backoff
- Provides task state tracking (pending, started, success, failure)
- Supports priority queues and rate limiting
- Integrates with Redis as a message broker

**Alternative: ARQ** — a lighter async task queue built on Redis. We may switch
to ARQ in the future for its simplicity and native async support. The refresh
orchestrator abstracts the task queue, so switching is a configuration change.

---

## Error Handling and Retry

Refresh jobs can fail for many reasons:

| Failure | Retry? | Behaviour |
|---------|--------|-----------|
| Source database unreachable | Yes, 3 retries with exponential backoff | 1s → 4s → 16s → fail |
| Source query timeout | Yes, 2 retries | Retry with same timeout |
| DuckDB write error (disk full) | No | Fail immediately, alert admin |
| Transform step error | No | Fail immediately, report which step and row |
| Calculated column cycle | No | Fail at validation, before any import |

**Full-or-nothing semantics:** If ANY table import fails, the entire refresh
is aborted. The staging file is deleted. The live file is untouched. This
prevents inconsistent state where some tables have new data and others have
old data.

---

## Monitoring

The refresh pipeline exposes Prometheus metrics:

| Metric | Type | What it measures |
|--------|------|-----------------|
| `magbi_refresh_duration_seconds` | Histogram | Total refresh time per dataset |
| `magbi_refresh_rows_imported` | Counter | Rows imported per table per refresh |
| `magbi_refresh_status` | Gauge | Current state (0=idle, 1=running, 2=failed) |
| `magbi_duckdb_file_size_bytes` | Gauge | Size of each live DuckDB file |
| `magbi_refresh_queue_depth` | Gauge | Number of pending refresh jobs |

Alerts:
- Refresh duration > 2x the historical average → warn
- Refresh failure → alert
- DuckDB file size > 80% of disk → critical

---

## Strengths

- **Zero-downtime refresh** — queries always see consistent data
- **Instant rollback** — rename the archive file back to live
- **Simple backup** — copy the DuckDB files. Done.
- **No shared state between datasets** — one dataset's problems cannot
  affect another
- **Parquet intermediate** — fast bulk loading with no persistent temp files

## Weaknesses & Risks

- **Single-writer limitation** — only one refresh per dataset at a time.
  Not a problem in practice (refreshes are infrequent), but limits future
  scenarios like parallel table imports into the same DuckDB file
- **Disk usage** — 5 archived versions means 6x the dataset size in disk space.
  A 10GB dataset uses 60GB of disk. Mitigated by configurable archive depth.
- **Full reimport** — for most tables, every refresh reimports all data.
  Incremental refresh helps but only for date-partitioned tables.
- **No real-time** — data is stale between refreshes. The minimum practical
  refresh interval is about 1 minute (for small datasets). For real-time
  needs, DirectQuery mode bypasses the import entirely.
- **Large file swap** — `os.rename()` is instant, but closing a 10GB DuckDB
  file flushes buffers, which can take seconds. Mitigated by explicit
  `connection.close()` before the rename.

---

## For Agents

1. Storage logic lives in `server/magbi/storage/`.
2. Refresh pipeline lives in `server/magbi/refresh/`.
3. Never write to a live DuckDB file. Always create a staging file, write to
   it, and swap.
4. Respect concurrency limits: 1/dataset, 3/workspace, 10/platform.
5. Always invalidate the Redis cache after a swap.
6. Always send the `dataset.refreshed` WebSocket event after a swap.
7. If a refresh fails, ensure the staging file is deleted (cleanup in a
   finally block).
8. Test refresh with a real source database — mocking the connector hides
   network timing issues.

---

## Further Reading

- [DuckDB Storage Format](https://duckdb.org/internals/storage)
- [Atomic File Operations on Linux](https://lwn.net/Articles/789600/)
- [Celery Documentation](https://docs.celeryq.dev/en/stable/)
- [MVCC Explained](https://en.wikipedia.org/wiki/Multiversion_concurrency_control)
- [Apache Parquet Format](https://parquet.apache.org/documentation/latest/)
