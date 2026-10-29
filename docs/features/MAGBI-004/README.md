# Feature: MAGBI-004 - DAX-lite compiler

Source: `docs/IMPLEMENTATION-PLAN.md` Sprint 4 (Week 5-7). FR: FR-023.
Deliverable: `SUM(Sales[Amount])` compiles to `SELECT SUM(amount) FROM sales`. `CALCULATE(SUM(Sales[Amount]), Product[Category] = "Electronics")` compiles to SQL with that filter applied. Time-intelligence functions compile to a rewritten date predicate.

## 1. Analysis
**Current state (verified)**: Sprint 3 stores measure and calculated-column expressions as text and lists `measure_expressions` and `rls_expressions` in `checks_deferred`. Saving a definition does not parse them. `server/magbi/dax/` is six stubs (`lexer.py`, `parser.py`, `binder.py`, `compiler.py`, `functions.py`, empty `__init__.py`). sqlglot is already used by the SQL Server connector. The query engine (`server/magbi/engine/`) is a stub; Sprint 5 owns group-by, totals, multi-fact queries, and RLS injection. The model already exposes `table()`, `measure()`, relationships, join paths, and date-table flags.

**Affected files**:
- `server/magbi/dax/lexer.py`, `parser.py`, `binder.py`, `compiler.py`, `functions.py`, `__init__.py`
- `server/magbi/model/validation.py` (measure and calculated-column expressions stop being deferred)
- `server/tests/test_dax/`
- `docs/kb/05-dax-lite.md`, `docs/architecture/DAX-LITE-SPEC.md` (status note)

**Design decisions**:
1. **This sprint compiles one expression to one DuckDB SQL statement.** It does not build the visual query (group-by, totals, multi-fact `FULL OUTER JOIN`, blank-row removal). Sprint 5 calls the compiler with a filter context. The compiler accepts an optional filter context so that call has somewhere to land; the default context is empty.
2. **Pipeline is lexer, Pratt parser, binder, compiler.** There is no separate IR module. `CALCULATE` is a filter context pushed down the recursive sqlglot walk. sqlglot emits DuckDB SQL only. T-SQL transpilation waits for DirectQuery.
3. **Supported functions** are the Sprint 4 list plus the grammar they sit on: `SUM`, `COUNT`, `COUNTA`, `COUNTROWS`, `AVERAGE`, `MIN`, `MAX`, `DISTINCTCOUNT`, `DIVIDE`, `IF`, `CALCULATE`, `ALL`, `REMOVEFILTERS`, `FILTER`, `AND`, `OR`, `NOT`, `TRUE`, `FALSE`, `BLANK`, `ISBLANK`. Also the operators `+ - * / = <> < > <= >= && ||`, the `IN { … }` set, parentheses, and `VAR` / `RETURN`. `SAMEPERIODLASTYEAR`, `DATEADD`, and `TOTALYTD` are the time-intelligence set.
4. **Everything else in the spec's function tables is unsupported this sprint**, including iterators (`SUMX` and the other X functions), `RELATED`, `KEEPFILTERS`, `ALLEXCEPT`, `VALUES`, `SWITCH`, math and text and date scalar functions beyond what an expression needs, and the other time-intelligence names. A curated list of known DAX names (spec section 14 and those deferred functions) produces "not supported in DAX-lite". Any other call name is "unknown function". The full list of ~350 DAX names is not shipped.
5. **References.** `Table[Column]` is a column. Bare `[Name]` is a measure. Table names match the model exactly, then case-insensitively when exactly one table folds to that name. Column and measure lookup follows the same rule. Measures are unique case-insensitively already. A measure reference is expanded up to a fixed depth; a cycle is an error naming the loop.
6. **Types and shape.** `SUM`, `AVERAGE`, `COUNT`, `COUNTA`, and `DISTINCTCOUNT` require a numeric column (`integer` or `decimal`). `MIN` and `MAX` also allow date, datetime, and string. A measure expression must contain an aggregation or a measure reference. A calculated-column expression is parsed in row context: an aggregation is an error, and the expression is not executed or written to DuckDB.
7. **CALCULATE.** Filter arguments of the form `Table[Column] <op> literal` (and `AND` / `OR` / `NOT` of those, and `IN`) replace the filter on the columns they mention. `ALL(Table)` and `ALL(Table[Column])` remove those filters. `FILTER(Table, predicate)` adds the predicate. Filters on a table other than the aggregated table become a `JOIN` along the active many-to-one path. No path, or an ambiguous path, is a compile error. `ALL` cannot see security filters because this sprint does not take a security context.
8. **BLANK is NULL.** Addition and subtraction treat NULL as 0 (`COALESCE`). `BLANK = BLANK` is compiled as both sides `IS NULL`. `DIVIDE(n, d)` is `n / NULLIF(d, 0)`. `DIVIDE(n, d, alt)` returns `alt` when the denominator is 0 or NULL. Raw `/` uses `NULLIF` so division by zero is NULL, not an error.
9. **Time intelligence requires a date table** (`is_date_table`, with `date_column`) and a relationship from the fact date column to that key. `SAMEPERIODLASTYEAR` shifts the date predicate by one year. `DATEADD` shifts by a number of `DAY`, `MONTH`, `QUARTER`, or `YEAR`. `TOTALYTD` expands the predicate from the start of the year through the latest date in context. Fiscal year uses `date_table.fiscal_year_start_month` (the year the fiscal year ends, same rule as Sprint 3). Missing date table, gaps, or a non-key date column are compile errors. The compiler emits the predicate; it does not scan `live.duckdb`.
10. **Errors block save.** `validate_model` parses and compiles every measure. Failures are errors with a stable code and a message that includes the 1-based line and column. `measure_expressions` leaves `checks_deferred`. `rls_expressions` stays deferred (RLS is still not enforced). Calculated columns are checked for shape only (decision 6). The existing `PUT` definition path already refuses to save when the report has errors, so no new endpoint is required.
11. **Identifiers in SQL are quoted** from the model names. The compiler does not trust the expression text as SQL. Only bound columns and bound literals reach sqlglot.

**Risks**:
- **CALCULATE filter replacement is easy to get subtly wrong.** Mitigation: one DuckDB execution test per supported function, on a tiny in-memory table, asserting the value and not only the SQL text.
- **Expanding measure references can recurse through CALCULATE.** A depth limit and a cycle check both fail the compile.
- **Time intelligence without a real calendar.** The predicate is calendar arithmetic. A model whose date table is not the generated one can still compile; gap checks stay in Sprint 3 validation and are not repeated here.
- **Joining the wrong side of a relationship.** Paths come from the existing `join_path`. The compiler does not invent joins.

**Assumptions**:
- One aggregated table per compiled expression. A measure that aggregates two fact tables is a compile error this sprint ("measures that combine two fact tables are compiled by the query engine").
- Filter context passed in by a future caller is a map of column to a simple predicate (eq, in, comparison, range). Sprint 5 defines the visual's filters. This sprint's tests build that map directly.
- `USERELATIONSHIP`, bidirectional filters, and many-to-many stay unsupported, matching the model.
- The Monaco editor, autocomplete, and "compiles to" panel are not this sprint.
- Calculated columns are not materialised on refresh.
- DirectQuery is not executed.

**Jira Tasks**:
| Key | Summary |
|-----|---------|
| TASK-1 | Lexer, parser, and parse errors |
| TASK-2 | Binder: names, types, cycles, measure shape |
| TASK-3 | Compiler: aggregates, CALCULATE, BLANK, joins |
| TASK-4 | Time intelligence predicates |
| TASK-5 | Validation on save, docs, and finalization |

---

## 2. Implementation Plan
| Subtask Key | Summary | Acceptance Criteria | Est. | Status |
|-------------|---------|---------------------|------|--------|
| SUB-1.1 | Lexer | Tokens for whitespace, comments, strings with doubled quotes, numbers, booleans, `Table[Column]`, `[Measure]`, keywords, operators, punctuation; each token has a 1-based line and column; table-driven tests | 3h | [x] |
| SUB-1.2 | Pratt parser | AST for literals, refs, calls, the precedence table, `IN {…}`, and `VAR` / `RETURN`; parentheses; the input is not mutated | 4h | [x] |
| SUB-1.3 | Parse errors | A known-unsupported function names itself and says it is not supported; an unknown call name says unknown function; errors carry line and column | 2h | [x] |
| SUB-2.1 | Name binding | Columns, measures, and tables resolve against `DatasetDefinition`; a missing name is an error; a measure cycle is an error naming the loop | 3h | [x] |
| SUB-2.2 | Types and shape | Numeric aggregations reject strings; `MIN`/`MAX` allow date and string; a measure without an aggregation is an error; a calculated column with an aggregation is an error | 3h | [x] |
| SUB-3.1 | Aggregate SQL | `SUM`, `COUNT`, `COUNTA`, `COUNTROWS`, `AVERAGE`, `MIN`, `MAX`, `DISTINCTCOUNT` emit DuckDB SQL; a column on a related table adds the join from `join_path`; the SQL runs on an in-memory DuckDB table and returns the expected number | 4h | [x] |
| SUB-3.2 | Scalars and BLANK | `DIVIDE`, `IF`, arithmetic, comparisons, and `IN` compile; NULL in `+` and `-` acts as 0; `DIVIDE` by zero is NULL; a DuckDB run covers `DIVIDE` and `IF` | 3h | [x] |
| SUB-3.3 | CALCULATE | A comparison filter replaces that column's filter; `ALL(Table)` and `ALL(Table[Column])` remove filters; `FILTER` adds a predicate; no path and an ambiguous path are errors; a DuckDB run shows the replaced filter changing the sum | 4h | [x] |
| SUB-4.1 | Time intelligence | `SAMEPERIODLASTYEAR`, `DATEADD`, and `TOTALYTD` rewrite the date predicate; they fail without a marked date table and a relationship to its key; fiscal year start month is honoured; a DuckDB run checks a year shift | 4h | [x] |
| SUB-5.1 | Save-time checks | `validate_model` compiles every measure and checks every calculated column; errors use stable codes and block the existing definition `PUT`; `measure_expressions` is no longer deferred; `rls_expressions` still is | 3h | [x] |
| SUB-5.2 | Docs | KB 05 and the DAX spec status note list the supported functions, the DuckDB-only target, and what stays in later sprints | 1.5h | [ ] |
| SUB-5.3 | Finalization | ruff, mypy strict, coverage over 80% for `dax` and the validation change; full regression; PR description | 1.5h | [ ] |

Order: 1.1, 1.2, 1.3, 2.1, 2.2, 3.1, 3.2, 3.3, 4.1, 5.1, 5.2, 5.3. Each subtask is code, tests, and one single-sentence commit. About 36 hours.

---

## 3. Execution Log
- [x] SUB-1.1: see git log. Column and measure references are one token. A keyword followed by a parenthesis stays an identifier.
- [x] SUB-1.2: see git log. Comparisons do not chain. AND binds tighter than OR. VAR / RETURN and IN sets are expressions.
- [x] SUB-1.3: see git log. Known DAX names that this sprint does not compile say they are not supported. Any other call name is an unknown function.
- [x] SUB-2.1: see git log. Exact names win. A case-insensitive match is used only when one model name folds to the text. Measure cycles name the loop.
- [x] SUB-2.2: see git log. SUM, COUNT, AVERAGE, and DISTINCTCOUNT require a numeric column. MIN and MAX also allow date and string. A calculated column is not executed.
- [x] SUB-3.1: see git log. One aggregate becomes one SELECT. An extra table is joined along the active relationship path. The SQL runs in DuckDB.
- [x] SUB-3.2: see git log. NULL in addition and subtraction acts as 0. DIVIDE by zero is NULL, or the alternate value when one is given. Two fact tables are rejected.
- [x] SUB-3.3: see git log. A comparison replaces the filter on that column. ALL removes filters. FILTER adds one. A missing or ambiguous relationship path is an error. DuckDB shows the replaced sum.
- [x] SUB-4.1: see git log. SAMEPERIODLASTYEAR, DATEADD, and TOTALYTD rewrite the date filter. They require one marked date table and its key. Fiscal year start month is honoured. DuckDB checks the year shift.
- [x] SUB-5.1: see git log. Every measure is compiled and every calculated column is shape-checked. Failures use stable codes and include line and column. Definition PUT returns 422 and does not bump the version. Row-level security stays deferred.
- [ ] SUB-5.2: (Commit hash)
- [ ] SUB-5.3: (Commit hash)

---

## 4. Definition of Done (DoD)
- [ ] Code is written and passes all local tests and lints
- [ ] Single-sentence commit rule followed for all commits
- [ ] SSOT README is fully updated
- [ ] PR description generated from this checklist
- [ ] `ruff check` and `mypy --strict` pass
- [ ] Coverage over 80% for `dax` and the validation change
- [ ] `SUM` and `CALCULATE` SQL both execute on DuckDB and return the expected values
- [ ] A measure with a syntax or type error is refused by definition `PUT`
- [ ] KB 05 updated to match the implementation
