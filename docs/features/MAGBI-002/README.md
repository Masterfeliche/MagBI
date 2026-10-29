# Feature: MAGBI-002 - SQL Server connector, import pipeline, atomic swap

Source: `docs/IMPLEMENTATION-PLAN.md` Sprint 2 (Week 2-3). FRs: FR-001, FR-005, FR-007, FR-081, FR-082.
Deliverable: point MagBI at a SQL Server, browse tables, import a table, find the data in a `.duckdb` file, query it with raw DuckDB SQL.

## 1. Analysis
**Current state (verified)**: Sprint 1 delivered `DuckDBStore` (live/vN/staging, `promote_staging`), `CredentialVault`, metadata ORM + Alembic `0001`, `/health/ready`. Still stubs: every file in `connectors/` except `base.py`, `refresh/importer.py`, `refresh/swap.py`, all `api/*.py` routers (empty and not mounted). `pyodbc` is declared but not in the local venv; `pyarrow` is not declared anywhere.

**Affected files**:
- `server/magbi/connectors/base.py` (replace async scaffold with the spec interface), `types.py` (new), `sqlserver.py`, `errors.py` (new)
- `server/magbi/refresh/importer.py`, `swap.py`, `orchestrator.py` (new `run_refresh`; Celery wiring stays in Sprint 8)
- `server/magbi/metadata/models.py` + `migrations/versions/0002_*.py` (new tables/column)
- `server/magbi/connections.py` (new: config, redaction, encryption service)
- `server/magbi/api/workspaces.py`, `datasets.py`, `connections.py` (new), `refresh.py`, `main.py` (mount under `/api/v1`)
- `server/pyproject.toml` (`pyarrow`, `pyodbc` already present), `server/Dockerfile` (Microsoft ODBC Driver 18), `deploy/docker-compose.yml` (`test` profile with SQL Server), `.github/workflows/ci.yml` (integration job)
- `server/tests/**` (new), `docs/kb/02-data-connectors.md`, `10-storage-refresh.md`, `docs/architecture/IMPORT-PIPELINE-SPEC.md`, `docs/guides/` (runbook)

**Design decisions**:
1. **Connectors are synchronous** (pyodbc is blocking). The spec's interface is sync; the existing async ABC is an unused stub and is replaced. API handlers call connectors via a thread pool; the importer runs in a worker thread/process. This also matches Celery in Sprint 8.
2. **Interface follows `IMPORT-PIPELINE-SPEC` 3.1**: `connect`, `list_schemas`, `list_tables`, `execute_query` (streams tuples), `get_row_count`, `get_dialect`, `close`, plus `test_connection` and `preview`. Typed `ConnectorError` with codes (`AUTH_FAILED`, `UNREACHABLE`, `TIMEOUT`, `NOT_FOUND`, `UNSUPPORTED`) that the API maps to JSON.
3. **No string-built SQL from user input.** Table and schema names must exist in the source catalog (`list_tables`); the SELECT is generated with sqlglot (`tsql`) with an explicit, quoted column list. ODBC connection-string values are brace-escaped so a value cannot inject `;Server=...`.
4. **Type mapping** per `DATASET-MODEL-SPEC` 4.1: ints to int64, `decimal(p,s)` to decimal128 (p<=38, else float64), `money` to decimal(19,4), `float/real` to float64, `bit` to bool, `date`, `datetime/datetime2/smalldatetime` to timestamp (microseconds; sub-microsecond precision truncated), `datetimeoffset` to UTC timestamp, `time`, `uniqueidentifier` to string, char types to string, `varbinary` to binary. Anything else (xml, geography, hierarchyid, sql_variant) is selected as `CONVERT(NVARCHAR(MAX), col)` and imported as string, with a warning in the refresh result. Never silently dropped.
5. **Streaming import**: fetch 10,000 rows, convert to an Arrow batch, insert into the staging DuckDB table, repeat. Memory stays constant. **Deviation from plan 2.2 and KB 02**: no Parquet intermediate yet. DuckDB inserts Arrow natively, and Parquet adds temp-file management for no measured gain. The batching sits behind one function so Parquet can be added if Sprint 11 profiling (NFR-001) asks for it.
6. **Sequential table import** this sprint (DuckDB has one writer; parallel imports from spec 8.3 can follow with measurements).
7. **Credentials**: password encrypted with `CredentialVault`, associated data = connection id, stored in `connections.secret_encrypted`; non-secret config in `config` JSON. API returns `"password": "***"`. Saving a password without `MAGBI_CREDENTIAL_KEY` fails with a clear error.
8. **Data model additions (migration 0002)**: `connections(id, workspace_id, name, kind, config, secret_encrypted, timestamps, unique(workspace_id,name))`, `dataset_refreshes(id, dataset_id, version, status, trigger, started_at, finished_at, result JSON, error)`, and a transitional `datasets.import_spec` JSON (`{connection_id, tables:[{schema,name,target}]}`). Sprint 3 replaces `import_spec` with the real dataset definition; it is documented as transitional.
9. **Refresh execution**: `run_refresh(refresh_id)` is a plain function (status lifecycle queued, running, succeeded/failed; sanitized error). For now the API runs it with FastAPI `BackgroundTasks`; Sprint 8 wraps the same function in a Celery task. One active refresh per dataset (409 otherwise). On startup, refreshes left `running` by a crash are marked failed.
10. **Swap**: `swap.py` wraps `promote_staging`, retries on `StoreError` with backoff (the Windows open-reader case from Sprint 1), then updates `datasets.current_version`. On any failure the staging file is discarded and the previous live file keeps serving.
11. **API shape**: follow `API-SERVICE-SPEC` (`/api/v1/workspaces/{wid}/...`), not the flat `/api/...` prefixes in the stubs. This resolves the prefix mismatch noted in MAGBI-001. Minimal create/list endpoints for workspaces and datasets are included only because a connection and a refresh need something to belong to; full CRUD stays in Sprint 3.5 and 7.6.
12. **Test source**: a SQL Server 2022 container (`mcr.microsoft.com/mssql/server`) behind a compose `test` profile, seeded with an ERP-shaped schema covering every mapped type, nulls, unicode and a 200k-row table. Integration tests are marked `integration` and skip unless the container is reachable. Unit tests use a fake connector and a mocked pyodbc, so the default `pytest` run needs no database.

**Risks**:
- **Unauthenticated API (Sprint 7 adds auth).** `connections/test` makes the server connect to any host and port the caller names, which is an SSRF and credential-probing vector. Mitigation: outside `dev` these endpoints return 503 unless `MAGBI_INSECURE_ADMIN_API=true`, and an optional `MAGBI_CONNECTOR_ALLOWED_HOSTS` allow-list is enforced when set. Both are removed or replaced by role checks in Sprint 7.
- **ODBC driver in the image.** `msodbcsql18` comes from Microsoft's apt repo and requires accepting their EULA (`ACCEPT_EULA=Y`); it adds roughly 100 MB and needs network at build time.
- **Integrated security** (Windows auth) cannot work from a Linux container. Supported in config for local Windows runs, documented as unsupported in Docker.
- **Encrypt on by default**: Driver 18 rejects self-signed certificates unless `trust_server_certificate` is true. The test container needs that flag; production should install a proper cert.
- **Precision loss**: `datetime2(7)` truncates to microseconds; `decimal` with precision over 38 becomes float64. Both are reported in the refresh result rather than hidden.
- **Windows swap** remains best-effort: retry then fail safely, never corrupt live data.
- **BackgroundTasks die with the process.** A restart mid-refresh leaves a stale `running` row (swept at startup) and a discarded staging file. Acceptable until Celery in Sprint 8.
- **Large `NVARCHAR(MAX)`/`VARBINARY(MAX)` columns** fetched in 10k-row batches can spike memory; batch size is configurable and the row cap per batch is by bytes as well as count.

**Assumptions**:
- Target is SQL Server 2016+ with ODBC Driver 18 (17 accepted as fallback). pymssql is not used.
- Only SQL Server is in scope; PostgreSQL, MySQL, CSV and DuckDB connectors stay stubs.
- No transforms yet: the import selects whole tables (Sprint 6 adds folding).
- The real MSD_ERP server is not touched by automated tests. A manual runbook documents how to point at it.
- Views are importable; synonyms and temp tables are out of scope.

**Jira Tasks**:
| Key | Summary |
|-----|---------|
| TASK-1 | Connector contract, type mapping and SQL Server connector (2.1) |
| TASK-2 | SQL Server test harness: container, seed data, integration tests, CI (2.6) |
| TASK-3 | Metadata for connections and refreshes, encrypted credentials (2.4, 2.5) |
| TASK-4 | Import pipeline, atomic swap and refresh runner (2.2, 2.3) |
| TASK-5 | REST API under `/api/v1`: browse, import, refresh (2.4, 2.5) |
| TASK-6 | Image, end-to-end verification, docs and finalization |

---

## 2. Implementation Plan
| Subtask Key | Summary | Acceptance Criteria | Est. | Status |
|-------------|---------|---------------------|------|--------|
| SUB-1.1 | Connector contract and errors | New `Connector` ABC per spec 3.1 with `SourceColumn/SourceTable`; `ConnectorError` with codes; fake connector in tests; old async stub removed | 2h | [x] |
| SUB-1.2 | Type mapping (`connectors/types.py`) | Every mapped SQL Server type resolves to DataType, Arrow and DuckDB types; decimal precision rules; unsupported types yield a CONVERT-to-string plan plus warning; table-driven tests | 3h | [x] |
| SUB-1.3 | SQL Server connector | Brace-escaped ODBC string; `test_connection` returns version, schemas, latency; list schemas/tables with columns, PK, estimated rows; streaming `execute_query`; pyodbc errors mapped to codes; sqlglot tsql SELECT builder; unit tests with mocked pyodbc | 6h | [x] |
| SUB-1.4 | Test harness and CI | `docker compose --profile test up` starts SQL Server with seed; `pytest -m integration` runs the connector against it and skips cleanly without it; CI job added | 4h | [x] |
| SUB-2.1 | Migration 0002 and models | `connections`, `dataset_refreshes`, `datasets.import_spec`; upgrade, downgrade, drift check pass on SQLite and Postgres | 3h | [x] |
| SUB-2.2 | Connection service | Create/update encrypts password with AAD = connection id; secrets never in responses, logs or errors; missing key rejected; host allow-list enforced | 3h | [x] |
| SUB-2.3 | Importer | Stream batches to staging DuckDB via Arrow; types per mapping; row count verified against source; warnings surfaced; progress callback; unit tests with fake connector, integration test on seed data | 6h | [x] |
| SUB-2.4 | Atomic swap | `swap_with_retry` promotes staging, updates `current_version`; reader-held file retries then fails safely; staging cleaned on any failure; old live untouched on failure | 3h | [x] |
| SUB-2.5 | Refresh runner | `run_refresh` drives queued/running/succeeded/failed; sanitized errors; one active refresh per dataset; stale `running` swept at startup | 4h | [ ] |
| SUB-3.1 | API plumbing | Routers mounted under `/api/v1` per spec; non-dev gate (`MAGBI_INSECURE_ADMIN_API`); `ConnectorError` to JSON with code; stub prefixes removed | 2h | [ ] |
| SUB-3.2 | Browse and CRUD endpoints | Workspaces and datasets create/list; connections test/create/list/get with `"password": "***"`; tables list, schema, preview (limit capped) | 5h | [ ] |
| SUB-3.3 | Refresh endpoints | `POST .../datasets/{id}/refresh` returns 202 with refresh id; `GET` status; 409 when one is active; tests with fake connector override | 3h | [ ] |
| SUB-4.1 | Image and compose | Dockerfile installs ODBC Driver 18; `docker compose build api` ok; api container connects to the SQL Server container | 3h | [ ] |
| SUB-4.2 | End-to-end verification | Seeded SQL Server to API to import to `live.duckdb`, queried with plain DuckDB; counts and sampled values match; integration test plus runbook in `docs/guides/` | 3h | [ ] |
| SUB-4.3 | Docs | KB 02 and 10 updated; spec corrections (`live.duckdb`, `/api/v1` paths, no-Parquet note) | 1.5h | [ ] |
| SUB-4.4 | Finalization | ruff, mypy strict, coverage over 80% for `connectors`, `refresh`, `api`; PR description | 1.5h | [ ] |

Order: 1.1 -> 1.2 -> 1.3 -> 1.4 -> 2.1 -> 2.2 -> 2.3 -> 2.4 -> 2.5 -> 3.1 -> 3.2 -> 3.3 -> 4.1 -> 4.2 -> 4.3 -> 4.4. Each subtask is Code + Test + one single-sentence commit. About 53 hours.

---

## 3. Execution Log
- [x] SUB-1.1: 2b93546 (committed together with SUB-1.2 as one commit; deviation from one-subtask-per-commit)
- [x] SUB-1.2: 2b93546 (see SUB-1.1)
- [x] SUB-1.3: see git log (feat(connectors): add SQL Server connector)
- [x] SUB-1.4: see git log (test(connectors): add SQL Server integration harness). Verified on SQL Server 2022: 14 live tests pass incl. geography/hierarchyid/sql_variant/xml degrade-to-string; datetimeoffset(7) rounds to 6 digits (expected, warned)
- [x] SUB-2.1: see git log (feat(metadata): add connections and dataset refreshes tables). Verified on Postgres 16: upgrade, alembic check, downgrade/upgrade, partial unique index rejects a second active refresh.
- [x] SUB-2.2: see git log (feat(connections): add encrypted connection service with host allow-list). 16 tests: AAD binding, redaction, no secret in errors, missing key, allow-list. Settings MAGBI_INSECURE_ADMIN_API and MAGBI_CONNECTOR_ALLOWED_HOSTS added (gate enforced in SUB-3.1).
- [x] SUB-2.3: see git log (feat(refresh): stream source tables into staging DuckDB via Arrow). 17 unit tests plus a live test: 200k rows streamed from SQL Server 2022 in about 8s, counts and values verified with plain DuckDB SQL. Row-count drift during import is a warning (source is live), written-vs-read mismatch fails.
- [x] SUB-2.4: see git log (feat(refresh): swap staging into place with retry and cleanup). FINDING: on Windows DuckDB does not block rename of an open live file (retry still kept for AV/backup locks). DuckDB caches databases per path in-process, so new connections see old data until old ones close; Sprint 4 query engine must close live connections on version change.
- [ ] SUB-2.5: (Commit hash)
- [ ] SUB-3.1: (Commit hash)
- [ ] SUB-3.2: (Commit hash)
- [ ] SUB-3.3: (Commit hash)
- [ ] SUB-4.1: (Commit hash)
- [ ] SUB-4.2: (Commit hash)
- [ ] SUB-4.3: (Commit hash)
- [ ] SUB-4.4: (Commit hash)

---

## 4. Definition of Done (DoD)
- [ ] Code is written and passes all local tests/lints
- [ ] Single-sentence commit rule followed for all commits
- [ ] SSOT README is fully updated
- [ ] PR description generated from this checklist
- [ ] `ruff check` and `mypy --strict` pass
- [ ] Coverage > 80% for `connectors`, `refresh`, `api`
- [ ] Integration tests pass against the SQL Server container
- [ ] Docker image builds with ODBC Driver 18 and imports a table end to end
- [ ] KB chapters 02 and 10 and the import spec updated to match the implementation
