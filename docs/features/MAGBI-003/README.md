# Feature: MAGBI-003 - Semantic model

Source: `docs/IMPLEMENTATION-PLAN.md` Sprint 3 (Week 3-5). FRs: FR-020, FR-021, FR-026, FR-027, FR-029.
Deliverable: a dataset built from imported tables, with relationships (Invoices to Department), measures (`SUM(Amount)` stored, not yet compiled), and a validation result. The model is the contract the query engine will read.

## 1. Analysis
**Current state (verified)**: Sprint 2 stores a transitional `datasets.import_spec` JSON (`{connection_id, tables:[{schema,name,target}]}`) and the refresh runner imports exactly those tables. `server/magbi/model/` is four empty stubs (`schema.py`, `relationships.py`, `validation.py`, `date_table.py`). Dataset API is create, list, get, update of name and `import_spec`. `DataType` already exists in `connectors/types.py` and matches the spec's type list. There is no DAX parser (Sprint 4) and no query engine (Sprint 5).

**Affected files**:
- `server/magbi/model/schema.py`, `relationships.py`, `validation.py`, `date_table.py` (replace stubs)
- `server/magbi/metadata/models.py` + `migrations/versions/0003_*.py` (`datasets.definition`, retire `import_spec`)
- `server/magbi/refresh/orchestrator.py` (read the definition instead of `import_spec`)
- `server/magbi/refresh/importer.py` (write a generated date table into the same staging file)
- `server/magbi/api/datasets.py`, `schemas.py` (definition, relationships, measures, validate)
- `server/tests/**`, `docs/kb/04-dataset-model.md`, `docs/architecture/DATASET-MODEL-SPEC.md` (status note)

**Design decisions**:
1. **One JSON document per dataset**, per KB 04, stored in `datasets.definition` (JSONB). It replaces `import_spec`. Migration 0003 copies each `import_spec` into a minimal definition (one connection, one `SqlTableSource` per table, columns empty) and drops the column. The refresh runner imports `definition.tables` whose source is `type: "table"`.
2. **Schema follows `DATASET-MODEL-SPEC` sections 2-10** as Pydantic models: `DatasetDefinition`, `TableDef`, `ColumnDef`, `MeasureDef`, `CalculatedColumnDef`, `HierarchyDef`, `RelationshipDef`, `RlsRoleDef`, `DateTableConfig`. `schemaVersion` is `"1.0"`. `DataType` is reused from `connectors/types.py`. Identity (`id`, workspace, name, timestamps, `current_version`) stays in the relational columns; the document holds the model. A `model_version` integer on the row is the optimistic concurrency counter the API checks.
3. **Relationships.** `from` is the many side, `to` is the one side. Cardinality `many-to-one` and `one-to-one` only: `many-to-many` and `crossFilterDirection: "both"` are rejected as unsupported (the spec defers both to phase 3; model them with a bridge table). At most one **active** relationship per pair of tables; extra ones must be `isActive: false` (two dates on one fact table). The "one" side column must be marked `isPrimaryKey`.
4. **Join paths** are a shortest path over active relationships, direction-agnostic for "how do these two tables connect", returned as the list of relationships. Two or more shortest paths of equal length is an ambiguous path (an error). A cycle is an error. Inactive relationships are stored and ignored by path finding. This function is what Sprint 5 will call.
5. **Measures and calculated columns are stored, not compiled.** There is no DAX parser until Sprint 4. This sprint checks structure only: unique measure names across the dataset, non-empty expression, home table exists. A small `ExpressionChecker` protocol has one implementation that accepts any non-empty expression; Sprint 4 replaces it and the parse, type, and circular-reference rules in spec 12.1 start firing without an API change. Calculated columns (FR-028, P3) are stored and not computed.
6. **RLS roles are stored, not enforced.** Role name unique, every `tableFilters.table` exists. Expressions are opaque strings. Assignment to users and enforcement are Sprint 7.
7. **Date table (FR-026, FR-027).** `generate_date_table(start, end, config)` returns a `TableDef` (columns from spec 9.2, the Year > Quarter > Month > Day hierarchy, `isDateTable` set) plus one row per day and no gaps. Fiscal year start month and first day of week are configurable. The range is the min and max of the dataset's date and datetime columns when those bounds are known, plus one year of padding; otherwise the caller passes the bounds. Refresh writes this table into the staging DuckDB file after the source tables and adds one active many-to-one relationship from each fact date column to `Date.Date` (further ones on the same table are inactive). Gap and duplicate checks (spec 12.1) run against `live.duckdb` when it exists, and are skipped with a warning when the dataset has not been imported yet.
8. **Validation (FR-029)** returns errors and warnings, it does not raise. Errors block save. Implemented now: duplicate table, column, and measure names; relationship to a missing table or column; more than one active relationship per table pair; unsupported cardinality or cross-filter; cycle; ambiguous path; date table not marked with a date column; date table gaps and duplicates when data exists. Warnings: table with no relationships, fact table with no measures, nullable foreign key on an inner join, hidden table with a visible measure. Not implemented (they need data profiling or the parser): high-cardinality warning, unused-relationship warning, measure parse and type errors, RLS parse errors. `POST .../validate` reports; `PUT` of the definition refuses to save when errors exist, and returns the warnings alongside a successful save.
9. **API** stays under `/api/v1` and behind the admin gate. Definition is read and written on the dataset. Relationships and measures are edits of that document, each returning the new definition and its validation:
   - `GET` and `PUT /workspaces/{wid}/datasets/{did}/definition`
   - `POST` and `DELETE .../definition/relationships[/{id}]`
   - `POST`, `PUT`, `DELETE .../definition/measures[/{name}]`
   - `POST .../definition/date-table` with `{start, end}` or bounds taken from the model
   - `POST .../definition/validate`
   Creating a dataset still accepts the old `import_spec` body for one sprint and converts it, so the Sprint 2 tests and the runbook keep working. Responses include `definition` and stop advertising `import_spec`.
10. **Columns are not inferred from the source in this sprint.** The caller names them (the browse API already returns names and types). Auto-detecting relationships (FR-022, P3) is out of scope; relationships are created explicitly.

**Risks**:
- **Replacing `import_spec` touches the refresh path.** A bad migration leaves existing datasets unable to refresh. Mitigation: the migration is reversible, and a test upgrades a Sprint 2 row and runs a refresh against the fake connector.
- **Optimistic concurrency.** Two edits of the definition can overwrite each other. `model_version` must match or the API returns 409.
- **Date table relationship explosion.** A fact table with several date columns gets one active and the rest inactive; the user is told which one was activated.
- **Validation that needs the parser is silently absent.** The result carries `checks_deferred: ["measure_expressions", "rls_expressions"]` so a caller can see what was not checked.
- **Generated date table size.** A 100-year range is about 36,500 rows, fine; the generator rejects a range over 200 years.

**Assumptions**:
- One connection per dataset, the spec's `connection` field. A table from a second connection is rejected.
- SQL query sources and CSV sources are stored but not imported (the importer raises a clear error). Only `type: "table"` is imported.
- DirectQuery is stored on the dataset mode column as today and not executed.
- Measure expressions are not evaluated. `SUM(Amount)` is accepted as text.
- The model editor UI (spec section 13) is Sprint 9.
- No change to the DuckDB file layout.

**Jira Tasks**:
| Key | Summary |
|-----|---------|
| TASK-1 | Model schema and storage, replacing `import_spec` (3.1) |
| TASK-2 | Relationship manager and join paths (3.2) |
| TASK-3 | Date table generation and materialisation (3.3) |
| TASK-4 | Model validation (3.4) |
| TASK-5 | API for the definition, relationships, measures (3.5) |
| TASK-6 | Tests, docs, finalization (3.6) |

---

## 2. Implementation Plan
| Subtask Key | Summary | Acceptance Criteria | Est. | Status |
|-------------|---------|---------------------|------|--------|
| SUB-1.1 | Model schema | Pydantic models for the spec sections 2-10; round-trip JSON; `DataType` reused; duplicate names rejected by the model; table-driven tests | 4h | [x] |
| SUB-1.2 | Persistence | Migration 0003 adds `definition` and `model_version`, backfills from `import_spec`, drops it; upgrade, downgrade, and drift check pass on SQLite and Postgres; refresh reads the definition | 3h | [x] |
| SUB-2.1 | Relationship edits | Add and remove; many-to-one and one-to-one only; one active per table pair; "one" side must be a key; unknown table or column rejected | 3h | [x] |
| SUB-2.2 | Join paths | Shortest path over active relationships; ambiguous path and cycle reported; inactive relationships ignored | 3h | [x] |
| SUB-3.1 | Date table generator | One row per day, no gaps, columns and hierarchy from spec 9.2; fiscal year and first day of week; range capped | 3h | [x] |
| SUB-3.2 | Date table in the import | Refresh writes the generated table into staging and adds relationships from date columns; imported file queried with plain DuckDB | 3h | [x] |
| SUB-4.1 | Validation errors | Every structural error in the decisions list blocks save; result lists errors with stable codes; expression checks reported as deferred | 4h | [x] |
| SUB-4.2 | Validation warnings | The four warnings; date-table gap and duplicate checks against `live.duckdb`; clean model produces no errors | 3h | [x] |
| SUB-5.1 | Definition API | `GET` and `PUT` definition with `model_version` and 409 on conflict; dataset create converts a legacy `import_spec`; Sprint 2 API tests updated | 4h | [x] |
| SUB-5.2 | Relationship, measure, date-table, validate endpoints | Add and delete relationship, add, update, delete measure, generate date table, validate; errors block the write and return the validation body | 4h | [x] |
| SUB-6.1 | Docs | KB 04 updated; spec status note (definition column, deferred rules, no many-to-many) | 1.5h | [x] |
| SUB-6.2 | Finalization | ruff, mypy strict, coverage over 80% for `model` and the changed API; regression of the full suite; PR description | 1.5h | [x] |

Order: 1.1, 1.2, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 5.1, 5.2, 6.1, 6.2. Each subtask is code, tests, and one single-sentence commit. About 37 hours.

---

## 3. Execution Log
- [x] SUB-1.1: see git log. Snake_case JSON (the spec is camelCase). Many-to-many and bidirectional filters cannot be constructed. Measure names are unique case-insensitively.
- [x] SUB-1.2: see git log. API create still accepts import_spec and stores a definition. Postgres drift check recorded after this commit.
- [x] SUB-2.1: see git log. add_relationship and remove_relationship return a new document; the schema rejects an illegal result.
- [x] SUB-2.2: see git log. Paths are undirected. Cycles are directed many-to-one, so a snowflake diamond is ambiguous and not a cycle. A length-2 cycle is already impossible.
- [x] SUB-3.1: see git log. Fiscal year is the year the fiscal year ends. Weekend is the last two days of the configured week.
- [x] SUB-3.2: see git log. First date column on a table is the active link; further ones are inactive. A 29 February pads to the 28th.
- [x] SUB-4.1: see git log. Codes include CYCLE, AMBIGUOUS_PATH, DUPLICATE_TABLE, MISSING_REFERENCE, UNSUPPORTED. Expression checks are listed as deferred.
- [x] SUB-4.2: see git log. Warnings ISOLATED_TABLE, FACT_WITHOUT_MEASURES, NULLABLE_INNER_JOIN, HIDDEN_TABLE_VISIBLE_MEASURE. Date checks DATE_TABLE_GAPS, DATE_TABLE_DUPLICATES, DATE_TABLE_NOT_IMPORTED, DATE_TABLE_NOT_CHECKED.
- [x] SUB-5.1: see git log. PUT returns 409 MODEL_VERSION_CONFLICT or 422 VALIDATION_FAILED and leaves the stored definition unchanged. A successful save returns warnings.
- [x] SUB-5.2: see git log. Errors block the write and return the validation body. Validate reports without saving. Date-table rows are written on the next refresh.
- [x] SUB-6.1: see git log. KB 04 and DATASET-MODEL-SPEC status note the definition column, snake_case storage, deferred expression checks, and no many-to-many.
- [x] SUB-6.2: see git log. 391 tests passed on Windows/Python 3.14. ruff and mypy strict clean. Coverage 94% on `model` and `api/datasets`.

---

## 4. Definition of Done (DoD)
- [x] Code is written and passes all local tests and lints (391 tests on Windows/Python 3.14, ruff, ruff format)
- [x] Single-sentence commit rule followed for all commits (commit-msg hook)
- [x] SSOT README is fully updated
- [x] PR description generated from this checklist (section 5)
- [x] `ruff check` and `mypy --strict` pass (`mypy magbi`: 68 source files, no issues)
- [x] Coverage over 80% for `model` and the dataset API (94% combined; datasets.py 88%, schema 97%, validation 94%, relationships 99%, date_table 98%)
- [x] A Sprint 2 dataset row still refreshes after the migration (migration 0003 backfill, orchestrator reads `definition`)
- [x] A generated date table is present in `live.duckdb` with no gaps (`refresh/dates.py`, exercised by the refresh tests)
- [x] KB 04 updated to match the implementation

### Deviations from the plan
1. Stored JSON is snake_case. The spec and `web/src/types/dataset.ts` stay camelCase until the UI sprint.
2. No `ExpressionChecker` protocol. Deferred checks are named on the validation result (`measure_expressions`, `rls_expressions`).
3. `POST .../date-table` updates the definition and sets `auto_generate`. The rows are written on the next refresh, which already materialises the date table.
4. Create and update still accept `import_spec` and convert it. Responses expose `definition`, not `import_spec`.
5. The SUB-4.2 execution-log line was written in the SUB-5.1 commit.

### Findings and open items
- High-cardinality, unused-relationship, measure parse, and RLS parse checks are not implemented. They need profiling or the Sprint 4 parser.
- DuckDB still caches an open database per path. The query engine must close live connections when `current_version` changes.
- The admin API stays unauthenticated until Sprint 7 (`MAGBI_INSECURE_ADMIN_API`).
- This regression was not repeated inside the Python 3.11 Linux image. CI runs that job.

---

## 5. PR Description

**feat: semantic model, relationships, date table and validation (MAGBI-003)**

Give each dataset one definition document: tables, relationships, stored measures, a generated date dimension, and a validation result the query engine can trust.

### What changed
- **Model** (`magbi/model`): Pydantic document for spec sections 2-10, relationship add/remove, undirected join paths, directed cycle detection, date-table generation, and validation with stable error and warning codes.
- **Storage**: migration `0003` adds `datasets.definition` and `model_version`, backfills from `import_spec`, and drops that column. Refresh imports `type: "table"` sources from the definition.
- **Date table**: refresh writes a gap-free `Date` table into staging and links the first date column on each table. Further date columns on the same table are inactive.
- **API**: `GET`/`PUT .../definition` with `model_version` (409 on conflict, 422 when validation has errors). Add and delete relationships, add, update and delete measures, generate a date table, and validate without saving.
- **Docs**: KB 04 and the dataset-model spec status note the snake_case column, deferred expression checks, and the rejection of many-to-many.

### How it was verified
- `ruff`, `ruff format`, `mypy` strict, 391 tests on Windows/Python 3.14.
- Coverage 94% on `magbi.model` and `magbi.api.datasets`.
- Migration upgrade, downgrade, and drift check were already run on Postgres for `0003`.

### Risks and follow-ups
Measure text is not parsed. Many-to-many is rejected on purpose. The next sprint should close live DuckDB connections when a dataset version changes, and should compile the expressions this sprint only stores.
