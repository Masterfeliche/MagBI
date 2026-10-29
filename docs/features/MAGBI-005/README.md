# Feature: MAGBI-005 - Query engine

Source: `docs/IMPLEMENTATION-PLAN.md` Sprint 5 (Week 7-9). Milestone 1.
Deliverable: a semantic query JSON returns a DataShapeResult from the dataset's `live.duckdb`.

## 1. Analysis
**Current state (verified)**: Sprint 4 compiles one measure to one DuckDB `SELECT` with no `GROUP BY`. `compile_measure` accepts an incoming filter context and extra tables to join, and it rejects a measure that aggregates two fact tables. `server/magbi/engine/` is nine stubs (`pipeline.py`, `filter_context.py`, `joins.py`, `grouping.py`, `sql_gen.py`, `executor.py`, `postprocess.py`, `cache.py`, empty `__init__.py`). `server/magbi/api/query.py` is an empty router and is not mounted. `join_path` already returns the only shortest active path. `DuckDBStore.open_live` opens `live.duckdb` read-only. Redis is a dependency and `redis_url` is configured; nothing in the engine calls it. RLS roles are stored and `rls_expressions` is still deferred. There is no embed token (Sprint 7). Two JSON shapes exist for the same idea: `web/src/types/query.ts` (what KB 06 says not to change) and `docs/architecture/QUERY-ENGINE-SPEC.md` section 2 (a different document).

**Affected files**:
- `server/magbi/engine/` (the pipeline)
- `server/magbi/dax/compiler.py` (aggregate expression plus the string filters the type already allows)
- `server/magbi/api/query.py`, `server/magbi/api/router.py`
- `server/tests/test_engine/`
- `web/src/types/query.ts` (optional totals and the roles request field only)
- `docs/kb/06-query-engine.md`, `docs/architecture/QUERY-ENGINE-SPEC.md` (status note)

**Design decisions**:
1. **The wire contract is `web/src/types/query.ts`.** A query has `from`, `select`, `where`, `orderBy`, and `limit`. A result has `columns`, `rows`, and `rowCount`. The architecture spec's `version` / `filters` / columnar `data` object is not the request or the response. `orderBy.select` is a 0-based index into `select`.
2. **One route, matching the other dataset routes.** `POST /api/v1/workspaces/{workspace_id}/datasets/{dataset_id}/query` with body `{ "query": SemanticQuery, "roles": [] }`. The spec's bare `POST /api/v1/query` and the batch endpoint wait. The admin gate stays as it is until Sprint 7.
3. **`from` is checked, not used as the SQL FROM list.** Every named table must exist. Joins come from the columns, measures, and filters the query actually uses. An empty `from` is valid.
4. **A select entry is a group column or a measure.** `column` without `aggregation` is grouped. `measure` is compiled. `aggregation` on a column becomes that function around the column (`SUM`, `COUNT`, `COUNTA`, `COUNTROWS`, `AVERAGE`, `MIN`, `MAX`, `DISTINCTCOUNT`). Both a measure and an aggregation, or neither, is an error.
5. **The compiler grows an aggregate result.** `compile_measure` stays the one-value `SELECT`. A new function returns the aggregate expression, the home fact table, and the tables that must be joined. The engine builds `SELECT` groups, `GROUP BY`, and `ORDER BY` around that expression. Filters stay inside the aggregate so `CALCULATE` still replaces them.
6. **User filters are the `where` array only.** Page, report, and slicer filters are already flattened by the caller. Comparison and `in` use the existing compiler operators. `notIn`, `contains`, `startsWith`, `isBlank`, and `isNotBlank` are added to that same filter list so `CALCULATE` can replace them too. `contains` and `startsWith` escape `%`, `_`, and `\`.
7. **Joins reuse `join_path`.** The engine does not write a second BFS. No path and an ambiguous path stay errors. Inactive relationships stay ignored.
8. **Two home tables become two grouped subqueries and a `FULL OUTER JOIN` on the group columns.** That is the chasm trap. One home table is one query. A stored measure that itself aggregates two facts is still an error. With no group columns, each measure is one scalar and the scalars sit side by side.
9. **Blank rows and totals.** A row whose every measure is NULL is dropped. `includeTotals: true` (added on the query, optional) re-runs the measures with the same filters and no `GROUP BY`, so a ratio or a distinct count is not the sum of the groups. The totals row is `totals` on the DSR, aligned with `columns`, with nulls in the group positions. Subtotals are not this sprint.
10. **Numbers stay raw.** `dataType` and `isMeasure` are filled. A measure `format` string is copied onto the column and is not applied. Dates are ISO strings. The default limit is 10,000 and the maximum is 100,000. `truncated` is true when the limit cut the result. `rowCount` is the number of rows returned.
11. **The cache is Redis, keyed by dataset id, `current_version`, and the canonical query.** TTL is 5 minutes. A refresh changes `current_version`, so old entries are never read. There is no user id in the key until Sprint 7. If Redis is down, the query still runs and is not cached. Tests use an in-memory stand-in. Each query opens `live.duckdb` read-only and closes it. A missing live file is `409 DATA_NOT_READY`.
12. **RLS is a separate predicate list.** The request may name roles that exist on the model. Each role's table-filter expression must be a comparison, `IN`, or `AND` of those. Those predicates are a `WHERE` on every subquery and are not passed into the replaceable filter context, so `ALL` and `REMOVEFILTERS` cannot remove them. An unknown role is an error. The API does not read an embed token. A role filter that is not a comparison is an error. `rls_expressions` stays deferred at save time.

**Risks**:
- **A `FULL OUTER JOIN` of grouped subqueries double-counts when the join keys are wrong.** Mitigation: one DuckDB test with two facts that share a dimension, asserting the grouped values and the ungrouped totals.
- **Putting user filters outside the aggregate breaks `CALCULATE`.** Mitigation: a test where `CALCULATE` replaces a query filter and the sum changes, including when `ALL` is used under an RLS predicate that must stay.
- **A held DuckDB connection blocks refresh on Windows.** Mitigation: open read-only, read the rows, close, then return. No process-wide connection cache.

**Assumptions**:
- DirectQuery and T-SQL are not executed.
- Calculated columns are not evaluated.
- Matrix subtotals, the batch endpoint, and embed-token RLS wait.
- The visual runtime sends one query per visual. Cross-filtering is more `where` entries.
- Display formatting happens in the client.

**Jira Tasks**:
| Key | Summary |
|-----|---------|
| TASK-1 | Query contract, binding, and filter context |
| TASK-2 | Joins and the chasm trap |
| TASK-3 | Grouped SQL, execution, and the DSR |
| TASK-4 | Cache, RLS, and the API |
| TASK-5 | Docs and finalization |

---

## 2. Implementation Plan
| Subtask Key | Summary | Acceptance Criteria | Est. | Status |
|-------------|---------|---------------------|------|--------|
| SUB-1.1 | Query schema and binding | A Pydantic query matches the TypeScript fields; unknown tables, columns, and measures fail with a stable code and the name; a select entry is a group column or one measure | 3h | [x] |
| SUB-1.2 | Filter context | `where` becomes the compiler filter list, including `notIn`, `contains`, `startsWith`, `isBlank`, and `isNotBlank`; a bad operator or value is an error | 3h | [x] |
| SUB-2.1 | Joins | Group and filter tables are joined from the home fact with `join_path`; no path and an ambiguous path are errors | 3h | [x] |
| SUB-2.2 | Chasm trap | Two home tables become two grouped subqueries `FULL OUTER JOIN`ed on the group columns; a DuckDB run shows each fact's sum, not a duplicated sum | 4h | [x] |
| SUB-3.1 | Grouped SQL | One fact becomes one `SELECT` with `GROUP BY`, `ORDER BY`, and `LIMIT`; the aggregate expression comes from the compiler; a query filter replaced by `CALCULATE` changes the value | 5h | [x] |
| SUB-3.2 | Execute and DSR | Rows come from DuckDB; all-null measure rows are dropped; `includeTotals` re-runs the measures without grouping; dates are ISO strings; `truncated` reflects the limit | 4h | [x] |
| SUB-4.1 | Cache | A second identical query is served from the cache; a new `current_version` misses; Redis being down still returns the query | 3h | [ ] |
| SUB-4.2 | RLS | Named roles add a `WHERE` that `ALL` does not remove; an unknown role and a non-comparison filter are errors | 4h | [ ] |
| SUB-5.1 | API | `POST` the workspace dataset query route returns the DSR; a missing dataset is 404; no `live.duckdb` is 409; a bad query is 422 and does not run SQL | 3h | [ ] |
| SUB-5.2 | Docs | KB 06 and the query-engine spec status note the TypeScript contract, DuckDB-only execution, request-supplied roles, and what stays later | 1.5h | [ ] |
| SUB-5.3 | Finalization | ruff, mypy strict, coverage over 80% for `engine` and the query route; full regression; PR description | 1.5h | [ ] |

Order: 1.1, 1.2, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 5.1, 5.2, 5.3. Each subtask is code, tests, and one single-sentence commit. About 35 hours.

---

## 3. Execution Log
- [x] SUB-1.1: see git log. The query matches the TypeScript fields. A select entry is a group column or one measure. Unknown names carry a stable code.
- [x] SUB-1.2: see git log. Query filters become compiler predicates. Text filters use CONTAINS and STARTS_WITH so the search text is literal. A date string becomes a date.
- [x] SUB-2.1: see git log. Extra tables are joined from the home fact with the existing path search. A missing or ambiguous path is an error.
- [x] SUB-2.2: see git log. Two home tables become grouped subqueries joined with FULL OUTER JOIN. DuckDB returns each fact's own sum.
- [x] SUB-3.1: see git log. One fact is one grouped SELECT. ORDER BY follows the select index and LIMIT is applied. CALCULATE replaces a query filter on the same column.
- [x] SUB-3.2: see git log. Rows are a DataShapeResult. All-null measure rows are dropped. Totals re-run the measures without grouping. A full limit sets truncated.
- [ ] SUB-4.1: (Commit hash)
- [ ] SUB-4.2: (Commit hash)
- [ ] SUB-5.1: (Commit hash)
- [ ] SUB-5.2: (Commit hash)
- [ ] SUB-5.3: (Commit hash)

---

## 4. Definition of Done (DoD)
- [ ] Code is written and passes all local tests and lints
- [ ] Single-sentence commit rule followed for all commits
- [ ] SSOT README is fully updated
- [ ] PR description generated from this checklist
- [ ] `ruff check` and `mypy --strict` pass
- [ ] Coverage over 80% for `engine` and the query route
- [ ] A grouped query and a two-fact query both execute on DuckDB and return the expected rows
- [ ] An RLS predicate survives `ALL`
- [ ] KB 06 updated to match the implementation
