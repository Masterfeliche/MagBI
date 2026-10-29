# Feature: MAGBI-006 - Transform engine

Source: `docs/IMPLEMENTATION-PLAN.md` Sprint 6 (Week 9-10). FR: FR-010, FR-011, FR-012, FR-013, FR-015.
Deliverable: a step list compiles to SQL where it can, and a preview returns 200 rows plus the fold boundary.

## 1. Analysis
**Current state (verified)**: `server/magbi/transforms/` is four stubs (`steps.py`, `folding.py`, `executor.py`, empty `__init__.py`). No route accepts a step list. Import still copies a whole source table into `live.duckdb`. The dataset definition has a table source and columns, and no transform recipe field. sqlglot is already used by the DAX compiler and the query engine. KB 03 and `docs/architecture/IMPORT-PIPELINE-SPEC.md` sections 5 and 6 describe the steps. The spec's TypeScript union has 21 variants because `uppercase` and `lowercase` share `CaseChangeStep`. The tables in KB 03 and the spec list those two names separately, and also list `groupBy`, so the named set is 22 type strings.

**Affected files**:
- `server/magbi/transforms/steps.py`, `folding.py`, `executor.py`, `__init__.py`
- `server/magbi/api/datasets.py` or a new preview route mounted beside it
- `server/tests/test_transforms/`
- `docs/kb/03-transform-engine.md`, `docs/architecture/IMPORT-PIPELINE-SPEC.md` (status note)

**Design decisions**:
1. **The step list is the spec's named set.** Each JSON object has `type` plus that type's fields. `uppercase` and `lowercase` are two types. `groupBy` is included. An unknown `type` is rejected. Steps are not stored on the definition in this sprint. The client sends them on the preview request.
2. **Folding walks from the first step and stops at the first step that cannot fold.** Everything after that index runs in Python, in order, on the rows the folded SQL returned. The boundary index is null when every step folds. `fillDown`, `pivot`, and `unpivot` do not fold. `splitColumn` folds for DuckDB with `string_split` and stops the fold for any other dialect.
3. **Preview executes on `live.duckdb`, dialect DuckDB.** The base query is `SELECT * FROM "Table"` using the model table name. The folded SQL is not sent to SQL Server. A later refresh can reuse the folder with another dialect. This sprint does not change the import runner.
4. **Identifiers are quoted from the step text. Values are literals.** `addColumn.expression` is parsed with sqlglot as one DuckDB expression. A statement, a second query, or text sqlglot cannot parse is an error. The expression AST is embedded. It is not concatenated into the SQL string.
5. **The folder tracks the output column list.** `selectColumns`, `removeColumns`, and `renameColumn` change that list. A reference to a column that is not in the list is an error. The preview still takes result names from the executed rows, so an added column appears.
6. **The Python executor only sees rows the folded query already limited.** Preview asks for 201 rows. 200 are returned. `truncated` is true when the extra row existed. `fillDown` uses that row order, so a `sortRows` before it is the order that fills. `unpivot` keeps the id columns and melts the value columns. `pivot` turns the key column's values into columns and aggregates duplicates with `sum`, `min`, `max`, or `count`.
7. **One route, matching the other dataset routes.** `POST /api/v1/workspaces/{workspace_id}/datasets/{dataset_id}/transforms/preview` with `{ "table", "steps" }`. A missing dataset is 404. No definition, an unknown table, or no `live.duckdb` is 409 or 422 with a stable code. A bad step is 422 and does not run SQL. The response is `columns`, `rows`, `rowCount`, `truncated`, `foldedStepCount`, `foldBoundary`, and `sql`.

**Risks**:
- **A step after a rename still using the old name compiles against the wrong column.** Mitigation: the column list is updated as each step folds, and a DuckDB test renames and then filters on the new name.
- **`addColumn` is an injection point.** Mitigation: the expression must parse as one expression. A test rejects a second statement.
- **`fillDown` on an unordered preview fills an arbitrary neighbour.** Mitigation: the test sorts first, asserts the filled value, and the response shows the fold boundary on `fillDown`.

**Assumptions**:
- The visual editor is Sprint 9. This sprint is the compiler, the Python steps, and the preview route.
- Import does not apply the recipe yet.
- DirectQuery and T-SQL execution are not run. The folder accepts a dialect argument and only DuckDB is executed.
- `addColumn` is a SQL expression, not DAX.

**Jira Tasks**:
| Key | Summary |
|-----|---------|
| TASK-1 | Step models |
| TASK-2 | Folding compiler |
| TASK-3 | Python executor and preview |
| TASK-4 | Docs and finalization |

---

## 2. Implementation Plan
| Subtask Key | Summary | Acceptance Criteria | Est. | Status |
|-------------|---------|---------------------|------|--------|
| SUB-1.1 | Step models | All 22 type strings parse into a discriminated union; a missing field and an unknown type fail; `uppercase` and `lowercase` are distinct | 3h | [x] |
| SUB-2.1 | Fold projection and filters | `filterRows`, `removeRows`, `selectColumns`, `removeColumns`, `renameColumn`, and `changeType` compile to DuckDB SQL and return the expected rows | 4h | [x] |
| SUB-2.2 | Fold value steps | `replaceValues`, `fillValue`, `mergeColumns`, `trimText`, `uppercase`, `lowercase`, `extractDate`, `addColumn`, and `splitColumn` fold; a bad `addColumn` expression is rejected | 4h | [x] |
| SUB-2.3 | Fold shape steps and the boundary | `sortRows`, `distinctRows`, `topN`, and `groupBy` fold; `fillDown`, `pivot`, and `unpivot` stop the fold and leave themselves and every later step unfolder | 3h | [x] |
| SUB-3.1 | Python steps | `fillDown`, `unpivot`, and `pivot` run on the rows of the folded SQL; a sort before `fillDown` is the order that fills; a mixed list reports the boundary | 4h | [x] |
| SUB-4.1 | Preview API | The workspace preview route returns at most 200 rows, `truncated`, the fold boundary, and the SQL; a missing dataset is 404; no imported table is 409; a bad step is 422 | 3h | [x] |
| SUB-4.2 | Docs | KB 03 and the import-spec status note list the foldable steps, DuckDB preview, and that the recipe is not stored yet | 1.5h | [x] |
| SUB-4.3 | Finalization | ruff, mypy strict, coverage over 80% for `transforms` and the preview route; full regression; PR description | 1.5h | [x] |

Order: 1.1, 2.1, 2.2, 2.3, 3.1, 4.1, 4.2, 4.3. Each subtask is code, tests, and one single-sentence commit. About 24 hours.

---

## 3. Execution Log
- [x] SUB-1.1: see git log. All 22 step types parse. An unknown type or a missing field is rejected. Uppercase and lowercase are distinct.
- [x] SUB-2.1: see git log. Filters, projection, rename, and casts compile to DuckDB SQL and return the expected rows. A missing column is an error.
- [x] SUB-2.2: see git log. Value steps fold to DuckDB functions. addColumn accepts one expression and rejects a statement. splitColumn folds only for DuckDB.
- [x] SUB-2.3: see git log. Sort, distinct, top, and group fold. fillDown, pivot, and unpivot stop the fold and keep every later step.
- [x] SUB-3.1: same commit as SUB-2.3. fillDown, unpivot, and pivot run after the folded SQL. A sort before fillDown is the order that fills. The boundary is the first Python step.
- [x] SUB-4.1: see git log. The workspace preview route returns at most 200 rows, the fold boundary, and the SQL. A missing dataset is 404. No imported data is 409. A bad step is 422.
- [x] SUB-4.2: see git log. KB 03 and the import spec say preview folds to DuckDB, where folding stops, and that the recipe is not stored or applied on import.
- [x] SUB-4.3: see git log. 459 tests on Windows/Python 3.14. ruff, ruff format, and mypy strict pass. Coverage of `magbi.transforms` and `magbi.api.transforms` is 89%.

---

## 4. Definition of Done (DoD)
- [x] Code is written and passes all local tests and lints (459 tests on Windows/Python 3.14.7, ruff, ruff format)
- [x] Single-sentence commit rule followed for all commits (commit-msg hook)
- [x] SSOT README is fully updated
- [x] PR description generated from this checklist (section 5)
- [x] `ruff check` and `mypy --strict` pass (`mypy magbi`: 74 source files, no issues)
- [x] Coverage over 80% for `transforms` and the preview route (89% combined, 490 statements; `api/transforms.py` 88%)
- [x] A folded step and a mixed fold/Python sequence both return the expected rows
- [x] The preview response includes the fold boundary
- [x] KB 03 updated to match the implementation

### Deviations from the plan
1. The named set is 22 type strings. The plan's "21" counts `uppercase` and `lowercase` as one `CaseChangeStep`. Both names are implemented.
2. The preview route lives in `api/transforms.py`, not `datasets.py`. The path is `POST /api/v1/workspaces/{workspace_id}/datasets/{dataset_id}/transforms/preview`.
3. Preview runs on `live.duckdb`. It does not send SQL to the source database. Import still copies the whole table, and the recipe is not stored.
4. `splitColumn` folds only for DuckDB. Another dialect stops the fold there.
5. SUB-3.1 is in the same commit as SUB-2.3.

### Findings and open items
- A step after the fold boundary that is not `fillDown`, `pivot`, or `unpivot` is an error. The preview does not re-fold those later steps yet.
- `addColumn` is one SQL expression, not DAX.
- The admin API stays unauthenticated until Sprint 7 (`MAGBI_INSECURE_ADMIN_API`).
- This regression was not repeated inside the Python 3.11 Linux image. CI runs that job.

---

## 5. PR Description

**feat: transform preview with query folding (MAGBI-006)**

Compile a list of transform steps to DuckDB SQL where possible, and preview the result.

### What changed
- **Steps** (`magbi/transforms`): 22 step types parse from the import-spec JSON. Unknown types and missing fields are rejected.
- **Folding**: filters, projection, rename, casts, value and text steps, dates, splits, sort, distinct, top, and group become one DuckDB `SELECT`. `fillDown`, `pivot`, and `unpivot` stop the fold.
- **Python**: those three steps run on the rows the folded SQL returned. A sort before `fillDown` is the order that fills.
- **API**: `POST .../transforms/preview` returns at most 200 rows, `truncated`, `foldBoundary`, `foldedStepCount`, and the SQL. Missing dataset is 404, no imported data is 409, a bad step is 422.
- **Docs**: KB 03 and the import spec record that the recipe is not stored and import does not apply it.

### How it was verified
- `ruff`, `ruff format`, and `mypy` strict on Windows/Python 3.14.7.
- 459 tests. DuckDB runs cover folded steps, a sort-then-fill, unpivot, and pivot.
- Coverage of `magbi.transforms` and `magbi.api.transforms` is 89%.

### Risks and follow-ups
Refresh does not apply the recipe, so a preview can disagree with the imported table until a later sprint stores the steps and folds them during import. A foldable step placed after `fillDown` is rejected rather than folded against the Python result. DirectQuery is not executed.
