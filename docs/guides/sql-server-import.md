# Runbook: import SQL Server tables into MagBI

Covers MAGBI-002: connect to SQL Server, browse tables, import them into a dataset's
`live.duckdb`, and check the result. Everything is under `/api/v1`.

## 1. Start the stack

```powershell
cd deploy
copy .env.example .env        # first time only, then fill in the key below
# python -c "from magbi.storage.credentials import generate_key; print(generate_key())"
docker compose up -d --build --wait api
```

`MAGBI_CREDENTIAL_KEY` in `deploy/.env` is required to save a connection password. The
API refuses to store one without it. Keep the key: losing it makes saved passwords
unreadable (re-enter them with `PUT .../connections/{id}`).

The API image contains Microsoft ODBC Driver 18. Building it accepts Microsoft's EULA
(`ACCEPT_EULA=Y` in the Dockerfile).

## 2. Try it against the test SQL Server (no real data needed)

```powershell
docker compose --profile test up -d --wait mssql-test     # SQL Server 2022, port 14333
cd ..\server; .\.venv\Scripts\python -m pytest -q          # seeds magbi_test, runs all tests
cd ..
$env:MSSQL_PASSWORD = "MagBI_Test_Passw0rd!"
server\.venv\Scripts\python scripts\e2e_import.py --host mssql-test --database magbi_test `
  --username sa --trust-server-certificate `
  --table 'sales."Order Lines"=order_lines' --table dbo.all_types
```

`--host` is resolved **by the API container**, so inside compose it is the service name
`mssql-test` (port 1433), not `localhost:14333`. The script prints the refresh result and
`DATASET_ID=...`.

## 3. Check the imported file with plain DuckDB

```powershell
cd deploy
docker compose exec -T api python -c "
import duckdb
c = duckdb.connect('/data/datasets/<DATASET_ID>/live.duckdb', read_only=True)
print(c.execute('SHOW TABLES').fetchall())
print(c.execute('SELECT count(*) FROM order_lines').fetchone())
"
```

Compare counts and a few values with the source. For the seed data, `order_lines` has
200,000 rows and `sum("Qty")` is 599,997.

## 4. Point it at a real server (for example MSD_ERP)

1. Create a **read-only SQL login** for MagBI (`db_datareader` on the one database).
   MagBI only ever sends `SELECT` and connects with `ApplicationIntent=ReadOnly`.
2. In `deploy/.env` set `MAGBI_CONNECTOR_ALLOWED_HOSTS=erp-sql.internal` so the API can
   only connect to that host.
3. Certificates: Driver 18 requires a trusted certificate. Install a proper one. Only use
   `"trust_server_certificate": true` for servers you control (dev, the test container).
4. Windows (integrated) authentication does not work from a Linux container. Use a SQL
   login, or run the API on a Windows host.
5. **Authentication of the MagBI API itself does not exist yet** (Sprint 7). Outside
   `MAGBI_ENVIRONMENT=dev` the admin API answers 503 until
   `MAGBI_INSECURE_ADMIN_API=true` is set. Do that only on a network you trust.
6. Run `POST /workspaces/{wid}/connections/test` first, then browse
   `.../connections/{id}/schemas` and `.../tables?schema=dbo`, then create a dataset with an
   `import_spec` and `POST .../datasets/{id}/refresh`.

## 5. API cheat sheet

| Call | Purpose |
|------|---------|
| `POST /workspaces` | create a workspace |
| `POST /workspaces/{w}/connections/test` | try a config without saving (`success: false` on connect failure) |
| `POST /workspaces/{w}/connections` | save (password encrypted, shown as `***`) |
| `GET  /workspaces/{w}/connections/{c}/schemas` | list schemas |
| `GET  /workspaces/{w}/connections/{c}/tables?schema=dbo` | tables, columns, PK, estimated rows, mapped type and warnings |
| `GET  /workspaces/{w}/connections/{c}/tables/{schema}/{table}/preview?limit=100` | first rows (max 1000) |
| `POST /workspaces/{w}/datasets` | body `{name, import_spec: {connection_id, tables: [{schema, name, target?}]}}` |
| `POST /workspaces/{w}/datasets/{d}/refresh` | returns 202 `{refresh_id}`; 409 if one is active |
| `GET  /workspaces/{w}/datasets/{d}/refresh/{id}` | `queued`, `running`, `succeeded`, `failed` (+ `result`, `error`) |
| `GET  /workspaces/{w}/datasets/{d}/refresh/history` | recent refreshes |

Errors are `{"error": {"code": "...", "message": "..."}}`. Source errors: `AUTH_FAILED` 400,
`NOT_FOUND` 404, `UNREACHABLE`/`QUERY_FAILED` 502, `TIMEOUT` 504, `INVALID_CONFIG` 422.

## 6. What the import does and does not do

- Streams 10,000-row batches into a staging file, then atomically swaps it in as
  `live.duckdb`. The previous file is archived as `v{N}.duckdb` (newest 5 kept). On any
  failure the old data keeps serving and staging is deleted.
- Types are mapped per `DATASET-MODEL-SPEC` 4.1. Unsupported types (`xml`, `geography`,
  `hierarchyid`, `sql_variant`) arrive as text with a warning in the refresh result.
  `datetimeoffset` is converted to UTC and rounded to microseconds. `decimal` above 38
  digits becomes double. Warnings are never silent.
- The source row count is compared with the rows imported. A change while importing (a
  live ERP) is reported as a warning, not a failure.
- Tables are imported one after another. Refreshes run in the API process (a restart
  marks a running one failed and the next trigger starts clean). Cancel and scheduling come
  with Celery in Sprint 8.

## 7. Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `INVALID_CONFIG ... MAGBI_CREDENTIAL_KEY` | key missing in `deploy/.env`; restart `api` after setting it |
| `INVALID_CONFIG ... not in the allowed host list` | host not in `MAGBI_CONNECTOR_ALLOWED_HOSTS` |
| `UNREACHABLE` from the container | used `localhost`; use the service name or a host reachable from the container |
| `UNREACHABLE` with a certificate message | server certificate not trusted; install a real one or set `trust_server_certificate` for dev |
| `AUTH_FAILED` | wrong login, or the login has no access to that database |
| 503 `ADMIN_API_DISABLED` | non-dev environment without `MAGBI_INSECURE_ADMIN_API=true` |
| refresh `failed: interrupted by a server restart` | the API restarted mid-refresh; trigger again |
