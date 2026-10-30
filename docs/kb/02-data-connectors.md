# 02 — Data Connectors

> **Status: In Progress** — the SQL Server connector, type mapping and streaming import are built
> (MAGBI-002, Sprint 2). PostgreSQL, MySQL, CSV/Excel and DuckDB connectors are still planned.
>
> **Implemented (Sprint 2), where it differs from the text below:**
> - Connectors are **synchronous** (pyodbc blocks); the API runs them in worker threads.
>   Interface: `connect`, `list_schemas`, `list_tables`, `execute_query` (streams tuples),
>   `get_row_count`, `get_dialect`, `build_select`, plus `test_connection` and `preview`.
>   Errors are `ConnectorError` with codes `AUTH_FAILED`, `UNREACHABLE`, `TIMEOUT`,
>   `NOT_FOUND`, `INVALID_CONFIG`, `UNSUPPORTED`, `NOT_CONNECTED`, `QUERY_FAILED`.
> - **No Parquet intermediate.** Rows are read in 10,000-row batches, converted to Arrow and inserted
>   straight into the staging DuckDB file. Parquet can be added behind one function if profiling asks.
> - SQL is generated with sqlglot (`tsql`) with quoted identifiers and only for tables that exist in
>   the source catalog. ODBC connection-string values are brace-escaped. The connection is read-only
>   (`ApplicationIntent=ReadOnly`, `SELECT`-only guard).
> - Unsupported types (`xml`, `geography`, `hierarchyid`, `sql_variant`) are imported as text with
>   a warning, never dropped. Verified on SQL Server 2022. `datetimeoffset` becomes UTC and is rounded
>   to microseconds; `decimal` above 38 digits becomes double.
> - Passwords are encrypted with AES-256-GCM bound to the connection id and shown as `***`.
> - Runbook: `docs/guides/sql-server-import.md`.

---

## What It Does

A data connector is a pluggable adapter that reads data from an external source
and brings it into MagBI. When a user clicks "Get Data," they pick a connector
(SQL Server, PostgreSQL, MySQL, CSV/Excel, or DuckDB file), provide connection
details, and MagBI shows them the available tables and columns.

Connectors are the first step in the data pipeline:

```
[Source DB] → Connector → [Raw Tables] → Transforms → [Shaped Tables] → DuckDB
```

### What a connector does

1. **Test connection** — verify credentials and network access
2. **List tables** — show what is available in the source
3. **Read schema** — return column names and types for a given table
4. **Read data** — stream rows from the source into the import pipeline

### What a connector does NOT do

- It does not transform data (that is the transform engine, chapter 03)
- It does not store data (that is DuckDB, chapter 10)
- It does not model data (that is the semantic model, chapter 04)

---

## Why This Approach

### The Connector ABC pattern

Every connector implements the same abstract base class:

```python
class Connector(ABC):
    async def test_connection(self) -> bool: ...
    async def get_tables(self) -> list[dict]: ...
    async def get_schema(self, table: str) -> list[dict]: ...
    async def read_table(self, table: str, *, limit: int | None = None): ...
```

This is the **Strategy pattern** — the import pipeline does not know or care
which database it is talking to. It calls `connector.read_table()` and gets
rows. Adding a new data source means writing a new class that implements these
four methods.

**Why not a plugin system with dynamic loading?** Plugins add complexity
(discovery, versioning, sandboxing) that we do not need yet. Five connectors
cover 90% of use cases. When we need more, we can add a plugin registry — but
the Connector ABC will stay the same.

### Alternatives rejected

- **ODBC/JDBC universal driver** — Possible, but ODBC driver installation is
  painful on Linux containers, and JDBC requires a JVM. Individual Python
  libraries (pyodbc, asyncpg, pymysql) are simpler to deploy.
- **Apache Arrow Flight** — Elegant for large data transfers, but requires the
  source to run a Flight server. Most databases don't.
- **Trino/Presto as a federation layer** — Powerful but adds an entire server
  to the stack. Overkill for reading from one source at a time.

---

## How It Works

### SQL Server Connector

**Library:** `pyodbc` (or `aioodbc` for async)

**Why pyodbc:** It is the standard Python ODBC driver. SQL Server is Microsoft's
database; ODBC is Microsoft's connectivity standard. pyodbc has been stable for
15+ years and handles every SQL Server version from 2008 to Azure SQL.

**Connection config:**
```python
{
    "host": "192.168.1.100",
    "port": 1433,
    "database": "MSD_ERP",
    "username": "readonly_user",
    "password": "<encrypted>",
    "driver": "ODBC Driver 18 for SQL Server",
    "trust_server_certificate": true
}
```

**How data flows:**
1. pyodbc opens a connection using the ODBC driver
2. `get_tables()` queries `INFORMATION_SCHEMA.TABLES`
3. `get_schema()` queries `INFORMATION_SCHEMA.COLUMNS` for the given table
4. `read_table()` executes `SELECT * FROM [schema].[table]` and yields rows
   in batches (fetchmany with a configurable batch size, default 10,000)

**Strengths:** Battle-tested, handles all SQL Server features (schemas, views,
synonyms). **Weakness:** ODBC driver must be installed in the container (adds
~100MB to the image). Sync-only by default (aioodbc wraps it in a thread pool).

### PostgreSQL Connector

**Library:** `asyncpg`

**Why asyncpg:** The fastest PostgreSQL driver for Python — 3x faster than
psycopg2 for bulk reads. It is natively async, which fits FastAPI's event loop.
No ODBC driver needed; it speaks the PostgreSQL wire protocol directly.

**How data flows:**
1. asyncpg opens a connection pool
2. `get_tables()` queries `information_schema.tables`
3. `read_table()` uses a server-side cursor (`DECLARE ... CURSOR`) and
   `FETCH 10000` in a loop to stream data without loading everything into memory

**Strengths:** Native async, fast binary protocol, no native dependencies.
**Weakness:** PostgreSQL-only (obviously). Connection string format differs from
ODBC.

### MySQL Connector

**Library:** `pymysql` (pure Python) or `aiomysql` (async wrapper)

**Why pymysql:** Pure Python, no compilation required, handles MySQL 5.7+ and
MariaDB. Lightweight and well-tested.

**How data flows:** Same pattern as PostgreSQL — `INFORMATION_SCHEMA` for
metadata, server-side cursor for streaming reads.

**Strengths:** Zero native dependencies, works on any platform.
**Weakness:** Slower than C-based drivers for very large tables. MySQL's type
system has quirks (e.g., `TINYINT(1)` is boolean, `DATETIME` vs `TIMESTAMP`).

### CSV / Excel Connector

**Library:** Python `csv` module + `openpyxl` (for .xlsx)

**Why not pandas?** Pandas loads the entire file into memory as a DataFrame.
For a 2GB CSV, that means 2GB+ of RAM. Instead, we use Python's built-in `csv`
reader (which streams) and `openpyxl` in read-only mode (which also streams).
The import pipeline writes batches to DuckDB as they arrive.

**How it works:**
1. User uploads a file (or provides a path on the server)
2. `get_schema()` reads the first 100 rows to infer column types
3. `read_table()` streams rows using a generator

**Type inference:** The connector reads a sample of rows, checks if each column
contains only integers, only decimals, only dates, or mixed text, and assigns
the most specific type. This is imperfect — a column that looks like integers in
the first 100 rows might contain text later. The user can override types in the
transform editor.

**Strengths:** No external dependencies for CSV; handles files from any source.
**Weakness:** Type inference is heuristic; Excel files with merged cells or
complex formatting may not import cleanly.

### DuckDB File Connector

**Library:** `duckdb` (Python bindings)

**Why:** Sometimes the data is already in a DuckDB file (exported from another
tool, or from a previous MagBI export). This connector reads it directly.

**How it works:** Opens the .duckdb file in read-only mode and queries it.
This is the simplest connector — DuckDB speaks to DuckDB.

---

## Key Concepts

### Connection pooling

Opening a database connection is expensive (TCP handshake, authentication, SSL
negotiation). Connection pooling keeps a set of open connections and reuses them.
asyncpg has built-in pooling; pyodbc connections are pooled by the ODBC driver
manager.

**Why it matters for MagBI:** During a data refresh, the connector opens a
connection and streams data for minutes. During user-initiated schema browsing,
connections are short-lived. Pooling handles both patterns efficiently.

### Streaming vs. bulk loading

Two ways to move data from a source to DuckDB:

1. **Streaming:** Read rows in batches (10k at a time), write each batch to
   DuckDB. Memory usage stays constant. Slower overall due to many round trips.
2. **Bulk:** Read everything into a Parquet file in memory (or on disk), then
   load the Parquet file into DuckDB in one shot. Faster overall, but requires
   enough memory to hold the entire table.

MagBI uses a hybrid: stream from the source in batches, accumulate into a
Parquet buffer (via pyarrow), flush to disk when the buffer exceeds 100MB, then
bulk-load all Parquet files into DuckDB. This balances memory and speed.

### Credential storage

Database passwords must never be stored in plain text. MagBI encrypts
credentials using AES-256-GCM with a key derived from the server's secret.
The encrypted blob is stored in PostgreSQL. The key never leaves the server
process.

**Why AES-256-GCM:** It provides both confidentiality (encryption) and
integrity (authentication). If someone tampers with the encrypted blob, GCM
detects it. AES-256 is approved for classified data by the NSA, which is more
than sufficient for database passwords.

---

## Strengths

- **Simple to add new connectors** — implement 4 methods, done
- **Async-native** — connectors do not block the API server
- **Streaming** — handles tables larger than available memory
- **Encrypted credentials** — passwords at rest are never plain text

## Weaknesses & Risks

- **Five connectors is not enough** — real-world users will want Snowflake,
  BigQuery, REST APIs, Google Sheets, etc. Each new connector is a maintenance
  burden.
- **Type mapping is lossy** — converting between SQL Server types, PostgreSQL
  types, and DuckDB types loses precision (e.g., SQL Server `MONEY` has no
  exact DuckDB equivalent).
- **Network errors during import** — if the source database goes down mid-import,
  the refresh fails. Retry logic helps but does not eliminate the risk.
- **No change data capture** — we reimport entire tables. For very large tables,
  this is slow. Incremental refresh (chapter 10) helps but only works with
  date-partitioned data.

---

## For Agents

1. Every connector lives in `server/magbi/connectors/`. One file per connector.
2. All connectors must implement the `Connector` ABC from `base.py`.
3. Never store credentials in the connector class. Read them from the encrypted
   credential store at connection time.
4. Stream data — never load an entire table into a Python list.
5. Handle connection errors gracefully — raise a typed exception that the API
   can translate to a user-friendly message.
6. Test each connector against a real database instance in the test suite (use
   Docker containers for CI).

---

## Further Reading

- [pyodbc documentation](https://github.com/mkleehammer/pyodbc)
- [asyncpg: A fast PostgreSQL client library](https://magicstack.github.io/asyncpg/)
- [DuckDB's data import pipeline](https://duckdb.org/docs/data/overview)
- [The Strategy Pattern (Refactoring Guru)](https://refactoring.guru/design-patterns/strategy)
- [AES-GCM explained](https://en.wikipedia.org/wiki/Galois/Counter_Mode)
