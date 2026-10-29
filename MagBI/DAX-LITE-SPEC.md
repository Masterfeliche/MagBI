# DAX-lite language specification

The formula language for v2. Users write measures and calculated columns in DAX
syntax; the engine compiles them to SQL and runs them on DuckDB (Import) or the
source database (DirectQuery). This document is the contract between the formula
editor, the parser, the binder, the compiler and the query planner.

| | |
|---|---|
| Written | 29 October 2026 |
| Status | Draft — not implemented |
| DAX coverage | ~40 functions; enough for every measure MSD has written so far |
| Compilation target | DuckDB SQL (primary), T-SQL (DirectQuery to SQL Server) |
| Sources | [SQLBI — Introducing CALCULATE](https://www.sqlbi.com/articles/introducing-calculate-in-dax/), [SQLBI — Filter context](https://www.sqlbi.com/articles/filter-context-in-dax-explained-visually/), [SQLBI — Context transition](https://www.sqlbi.com/articles/understanding-context-transition-in-dax/), [dax.guide](https://dax.guide/), [Microsoft Learn — Time intelligence](https://learn.microsoft.com/en-us/training/modules/dax-power-bi-time-intelligence/2-functions), [SQLBI — Auto-exist](https://sqlbi.com/articles/understanding-dax-auto-exist) |

---

## Contents

1. [Design principles](#1-design-principles)
2. [Lexical grammar](#2-lexical-grammar)
3. [Expression grammar](#3-expression-grammar)
4. [Two contexts: row and filter](#4-two-contexts-row-and-filter)
5. [CALCULATE — the core of the language](#5-calculate--the-core-of-the-language)
6. [Context transition](#6-context-transition)
7. [Function reference (all ~40)](#7-function-reference)
8. [Time intelligence](#8-time-intelligence)
9. [Compilation to SQL](#9-compilation-to-sql)
10. [BLANK semantics](#10-blank-semantics)
11. [Auto-exist and blank-row removal](#11-auto-exist-and-blank-row-removal)
12. [Totals and subtotals](#12-totals-and-subtotals)
13. [Error model](#13-error-model)
14. [What is deliberately excluded](#14-what-is-deliberately-excluded)
15. [Golden tests](#15-golden-tests)
16. [Appendix: grammar in EBNF](#16-appendix-grammar-in-ebnf)

---

## 1. Design principles

1. **DAX syntax, SQL semantics.** A user who knows DAX can write measures
   without relearning. But every expression compiles to SQL, so the semantics
   are defined by what the generated SQL does, not by what DAX would do in edge
   cases we haven't tested.

2. **Closed set of functions.** The parser recognises every DAX function name
   (all ~350) and gives a clear error for unsupported ones: *"`ADDCOLUMNS` is
   not supported in DAX-lite. Consider creating a SQL view instead."* Unknown
   names get a generic parse error.

3. **Measures are aggregate; calculated columns are row-level.** A measure
   always contains an aggregation (`SUM`, `COUNT`, …) or a reference to another
   measure (which does). A calculated column never does — it has row context
   and can use `RELATED` to look up a value from a related table.

4. **No table-valued expressions in measures.** You cannot build a virtual
   table inside a measure (`ADDCOLUMNS`, `SUMMARIZE`, `GENERATE`, `TOPN`,
   `UNION`, `EXCEPT`, `INTERSECT`). This is the biggest limitation, and the
   one that keeps compilation tractable.

5. **Compile errors, not runtime surprises.** Type mismatches, circular
   references, ambiguous column names, and unreachable relationships are
   caught at model save time, not when a user opens a dashboard.

---

## 2. Lexical grammar

Tokens, in precedence order:

| Token | Pattern | Examples |
|---|---|---|
| **Whitespace** | `[ \t\r\n]+` | Skipped |
| **Line comment** | `//` to end of line | `// revenue measure` |
| **Block comment** | `/* … */` (no nesting) | |
| **String literal** | `"…"` with `""` as escaped quote | `"Completed"`, `"it""s"` |
| **Number literal** | `[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?` | `42`, `3.14`, `1e6` |
| **Date literal** | Not a token — use `DATE(y, m, d)` | |
| **Boolean** | `TRUE` / `FALSE` (case-insensitive) | |
| **Table reference** | `'TableName'` (single-quoted) or bare `TableName` | `'Date'`, `Trip` |
| **Column reference** | `TableName[ColumnName]` or `'Table Name'[Column]` | `Trip[Status]`, `'Date'[Year]` |
| **Measure reference** | `[MeasureName]` (no table prefix in scope) | `[Trips]`, `[Revenue]` |
| **Function name** | Identifier followed by `(` | `SUM`, `CALCULATE` |
| **Keyword** | `VAR`, `RETURN`, `TRUE`, `FALSE`, `BLANK`, `IN`, `NOT`, `AND`, `OR` | Case-insensitive |
| **Operator** | `+ - * / = <> < > <= >= && ||` | |
| **Punctuation** | `( ) [ ] , .` | |
| **Identifier** | `[A-Za-z_][A-Za-z0-9_ ]*` (spaces allowed in brackets) | |

Column references always carry their table: `Trip[DistanceKm]`, not just
`[DistanceKm]`. Measure references are always bare: `[Trips]`. This removes
the ambiguity that DAX has (where `[Name]` might be a column or a measure
depending on context).

---

## 3. Expression grammar

Pratt parser with these precedence levels (lowest to highest):

| Level | Operators | Associativity |
|---|---|---|
| 1 | `OR`, `||` | Left |
| 2 | `AND`, `&&` | Left |
| 3 | `NOT` (prefix) | Right |
| 4 | `=`, `<>`, `<`, `>`, `<=`, `>=`, `IN` | Left (non-chaining) |
| 5 | `+`, `-` (binary) | Left |
| 6 | `*`, `/` | Left |
| 7 | `-` (unary prefix) | Right |
| 8 | Function call, column ref, measure ref, literal, `(expr)` | — |

### VAR / RETURN

```
VAR _name = expr
VAR _other = expr
RETURN resultExpr
```

Variables are immutable and evaluated once (the SQL compiler emits a CTE or
subquery). They are scoped to the `RETURN` expression. Names conventionally
start with `_` but this is not enforced.

### IF / SWITCH

```
IF ( condition, trueExpr, falseExpr )
IF ( condition, trueExpr )              -- falseExpr defaults to BLANK()

SWITCH ( TRUE(),
    condition1, result1,
    condition2, result2,
    elseResult
)
SWITCH ( expr,
    value1, result1,
    value2, result2,
    elseResult
)
```

### IN operator

```
Trip[Status] IN { "Completed", "Approved" }
```

The `{ … }` is syntactic sugar for a set literal, not a table constructor.
It compiles to `IN (…)` in SQL.

---

## 4. Two contexts: row and filter

Every DAX-lite expression is evaluated under a **context** — the set of
constraints that determine which rows contribute to the result. Understanding
these two contexts is essential to understanding how measures work.

### 4.1 Filter context

A set of active filters, each constraining one column to a set of allowed
values (or a predicate). Filter context is what a visual cell provides: the
combination of its row headers, column headers, slicer selections, page
filters, report filters and RLS predicates.

Represented internally as:

```typescript
type FilterContext = Map<ColumnRef, Predicate>;
// e.g. { "Date[Year]": Eq(2026), "Vehicle[Type]": In("Truck", "Bus") }
```

Filters are combined with AND: a row must satisfy every filter in the context
to be included.

**Filter propagation.** Filters flow through relationships from the one side
to the many side (dimension → fact). A filter on `Directorate[Name]` propagates
to `Trip` through the relationship `Trip.DepartmentGuid → Directorate.DepartmentGuid`,
so `SUM(Trip[DistanceKm])` sees only the rows for that directorate. This is
automatic — the compiler walks the relationship graph.

### 4.2 Row context

An iteration over a table's rows. Each iteration exposes the current row's
column values. Created by:
- A **calculated column** definition (iterates the host table's rows).
- An **iterator function** (`SUMX`, `AVERAGEX`, `MINX`, `MAXX`, `COUNTX`,
  `FILTER`).

Inside row context, `Trip[DistanceKm]` means "the DistanceKm value of the
current row", not "all values of DistanceKm under the current filters".

**Row context does NOT filter.** This is the key difference from filter
context. Inside `SUMX(Trip, Trip[DistanceKm] * 2)`, the expression
`Trip[DistanceKm]` reads the current row, but a reference to another table
(`Vehicle[FuelPrice]`) does not automatically filter to the related row —
you need `RELATED(Vehicle[FuelPrice])` to look it up.

### 4.3 How visuals create context

When a visual cell is computed — say, "Trips for Operations in January 2026" —
the engine builds this filter context:

```
{
  "Directorate[Name]": Eq("Operations"),
  "Date[Month]": Eq("2026-01"),
}
```

Then evaluates `[Trips]` (which is `COUNTROWS(Trip)`) under that context. The
compiler generates:

```sql
SELECT COUNT(*) FROM Trip t
  JOIN Directorate d ON … JOIN Date dt ON …
  WHERE d.Name = 'Operations' AND dt.Month = '2026-01'
```

Each cell is one evaluation. The query planner groups all cells into one
`GROUP BY` query when possible (§9).

---

## 5. CALCULATE — the core of the language

`CALCULATE` is the only way to modify filter context. Every other filter
manipulation function (`ALL`, `ALLEXCEPT`, `REMOVEFILTERS`, `KEEPFILTERS`,
`VALUES`, time intelligence) works as an argument to `CALCULATE`.

### 5.1 Syntax

```
CALCULATE ( expression, filter1, filter2, … )
```

Each filter argument is one of:
- A **boolean expression** referencing a single column: `Trip[Status] = "Completed"`
- A **table function** that returns a filter: `ALL(Vehicle[Type])`,
  `SAMEPERIODLASTYEAR('Date'[Date])`
- `KEEPFILTERS( filter )` — modifies the behaviour of the filter it wraps

### 5.2 Evaluation rules (in order)

This is the exact algorithm, step by step:

1. **Start with the current filter context** (the one the visual cell provides,
   or the outer CALCULATE provides).

2. **Evaluate each filter argument** against the **outer** filter context (not
   the one being built). This matters: a filter argument sees the same filters
   the expression would see without CALCULATE.

3. **For each filter argument** (in any order — order does not matter):
   - Determine which column(s) the filter targets.
   - **REPLACE** the existing filter on those column(s) with the new filter.
     This is the default: `CALCULATE([Trips], Date[Year] = 2025)` **removes**
     any existing filter on `Date[Year]` and **replaces** it with `= 2025`.
   - Filters on **other** columns are untouched.
   - If the argument is wrapped in `KEEPFILTERS`, **intersect** instead of
     replace: the new filter is ANDed with the existing filter on that column.

4. **If there is a row context** (because CALCULATE is inside an iterator),
   perform **context transition** (§6): the current row's column values become
   filters in the new context.

5. **Evaluate the expression** under the new filter context.

### 5.3 Examples

```dax
-- Replaces any existing Year filter with 2025
Prior Year Trips = CALCULATE ( [Trips], Date[Year] = 2025 )

-- Removes ALL filters on Vehicle[Type], so [Trips] counts across all types
All Types = CALCULATE ( [Trips], ALL(Vehicle[Type]) )

-- Removes ALL filters from the Directorate table (every column)
All Directorates = CALCULATE ( [Trips], ALL(Directorate) )

-- KEEPFILTERS: intersects with the existing Year filter
-- If the visual shows 2026, this returns 0 (2025 AND 2026 = empty)
KF Example = CALCULATE ( [Trips], KEEPFILTERS(Date[Year] = 2025) )

-- Share of total: the denominator removes the axis grouping
Share = DIVIDE (
    [Trips],
    CALCULATE ( [Trips], ALL(Directorate[Name]) )
)
```

### 5.4 Nested CALCULATE

Each CALCULATE creates a new scope. The inner CALCULATE's filter arguments
are evaluated against the **outer CALCULATE's result** (not the original
visual context). This follows from rule 1 + 2 above.

```dax
-- Trips in "Completed" status, ignoring the visual's Year filter
Always Completed = CALCULATE (
    CALCULATE ( [Trips], Trip[Status] = "Completed" ),
    ALL(Date[Year])
)
```

---

## 6. Context transition

When CALCULATE is called inside a row context (an iterator or a calculated
column), it converts the current row into filter context. This is called
**context transition**.

### 6.1 The rules

1. For each column of the table being iterated, a filter `Column = currentRowValue`
   is added to the new filter context.
2. These row-derived filters **replace** existing filters on those columns
   (same replacement rule as §5.2 step 3).
3. The original row context is **discarded** — the expression inside CALCULATE
   no longer has row context (unless it creates a new one with its own iterator).

### 6.2 Implicit context transition

A **measure reference** implicitly wraps itself in CALCULATE. So inside
`SUMX(Trip, [Revenue])`, the `[Revenue]` measure is evaluated with the current
Trip row as filter context. This is what makes measures "work" inside iterators.

In DAX-lite, this implicit CALCULATE is the only form of context transition
a user encounters. We do not support explicit `CALCULATE` inside iterators for
purposes other than calling a measure or applying additional filters.

### 6.3 Compilation

Context transition over a single fact table compiles naturally to SQL's
aggregate-per-row pattern. For example:

```dax
Weighted Distance = SUMX ( Trip, Trip[DistanceKm] * RELATED(Vehicle[Weight]) )
```

Compiles to:

```sql
SUM(t.DistanceKm * v.Weight)
-- with Trip t JOIN Vehicle v already in the FROM clause
```

The iterator `SUMX(Table, scalar_expr)` compiles to `SUM(scalar_expr)` when:
- The expression uses only columns from the iterated table and `RELATED` lookups.
- There is no nested CALCULATE with additional filters.

When there IS a nested measure reference with its own filters, the compiler
emits a correlated subquery or a window function.

---

## 7. Function reference

### 7.1 Aggregation functions

These take a column and produce one value under the current filter context.

| Function | Signature | SQL | Notes |
|---|---|---|---|
| `SUM` | `SUM(T[c])` | `SUM(c)` | Column must be numeric |
| `AVERAGE` | `AVERAGE(T[c])` | `AVG(c)` | |
| `MIN` | `MIN(T[c])` | `MIN(c)` | Also works with dates and strings |
| `MAX` | `MAX(T[c])` | `MAX(c)` | |
| `COUNT` | `COUNT(T[c])` | `COUNT(c)` | Non-BLANK values only |
| `COUNTA` | `COUNTA(T[c])` | `COUNT(c)` | Same as COUNT in SQL (NULLs excluded) |
| `COUNTROWS` | `COUNTROWS(T)` | `COUNT(*)` | Counts rows of the table |
| `DISTINCTCOUNT` | `DISTINCTCOUNT(T[c])` | `COUNT(DISTINCT c)` | |
| `MEDIAN` | `MEDIAN(T[c])` | `MEDIAN(c)` | DuckDB native; T-SQL: `PERCENTILE_CONT(0.5)` |

### 7.2 Iterator functions (X-functions)

These iterate a table row by row, evaluate a scalar expression per row (in row
context), and aggregate the results.

| Function | Signature | SQL | Notes |
|---|---|---|---|
| `SUMX` | `SUMX(T, expr)` | `SUM(expr)` | `expr` can use `T[col]` and `RELATED(…)` |
| `AVERAGEX` | `AVERAGEX(T, expr)` | `AVG(expr)` | |
| `MINX` | `MINX(T, expr)` | `MIN(expr)` | |
| `MAXX` | `MAXX(T, expr)` | `MAX(expr)` | |
| `COUNTX` | `COUNTX(T, expr)` | `COUNT(CASE WHEN expr IS NOT NULL THEN 1 END)` | Counts non-BLANK results |

**Restriction:** The table argument must be a physical table name (optionally
wrapped in `FILTER`), not a table expression. The scalar expression can
reference columns of that table and `RELATED()` lookups. Measure references
inside the expression invoke context transition (§6.2).

### 7.3 Filter modifier functions

Used as arguments to CALCULATE.

| Function | Signature | Effect on filter context |
|---|---|---|
| `ALL(T)` | `ALL(Table)` | Removes all filters from every column of T |
| `ALL(T[c])` | `ALL(Table[Column])` | Removes the filter on that one column |
| `ALL(T[c1], T[c2])` | multiple columns | Removes filters on those columns |
| `ALLEXCEPT(T, T[c])` | keep only c's filter | Removes filters on every column of T **except** c |
| `REMOVEFILTERS()` | `REMOVEFILTERS(T)` or `(T[c])` | Synonym for `ALL` in this position |
| `KEEPFILTERS(filter)` | wraps a filter argument | Changes CALCULATE's default replace to intersect |
| `FILTER(T, predicate)` | returns filtered table | Used as a CALCULATE argument; adds the predicate as a filter. The table T determines which columns are affected |
| `VALUES(T[c])` | returns distinct values of c | Used to test `HASONEVALUE`, `SELECTEDVALUE`, or as a CALCULATE filter |

### 7.4 Information functions

| Function | Signature | Returns | SQL |
|---|---|---|---|
| `HASONEVALUE(T[c])` | column ref | TRUE if exactly one distinct value in context | Compiled at query time using the known filter |
| `SELECTEDVALUE(T[c])` | column ref | The value if `HASONEVALUE`, else BLANK | Same |
| `SELECTEDVALUE(T[c], alt)` | column ref + default | The value if one, else alt | |
| `ISFILTERED(T[c])` | column ref | TRUE if column has an active filter | Compile-time check |
| `ISBLANK(expr)` | scalar | TRUE if expr is BLANK/NULL | `expr IS NULL` |
| `BLANK()` | — | The BLANK value | `NULL` |
| `IFERROR(expr, alt)` | scalar, scalar | alt if expr errors | `COALESCE(TRY(expr), alt)` in DuckDB |

### 7.5 Logic functions

| Function | Signature | SQL |
|---|---|---|
| `IF(cond, true, false)` | 3 args (false optional → BLANK) | `CASE WHEN cond THEN true ELSE false END` |
| `SWITCH(expr, v1, r1, …, else)` | alternating value/result pairs | `CASE expr WHEN v1 THEN r1 … ELSE else END` |
| `SWITCH(TRUE(), c1, r1, …, else)` | alternating condition/result | `CASE WHEN c1 THEN r1 … ELSE else END` |
| `AND(a, b)` / `a && b` | two booleans | `a AND b` |
| `OR(a, b)` / `a \|\| b` | two booleans | `a OR b` |
| `NOT(a)` | one boolean | `NOT a` |
| `COALESCE(a, b, …)` | variadic | `COALESCE(a, b, …)` |
| `TRUE()` / `FALSE()` | — | `TRUE` / `FALSE` |

### 7.6 Math functions

| Function | SQL |
|---|---|
| `DIVIDE(num, den)` | `num / NULLIF(den, 0)` — returns BLANK on division by zero, not error |
| `DIVIDE(num, den, alt)` | `CASE WHEN den = 0 OR den IS NULL THEN alt ELSE num / den END` |
| `ABS(x)` | `ABS(x)` |
| `ROUND(x, n)` | `ROUND(x, n)` |
| `INT(x)` | `CAST(FLOOR(x) AS INTEGER)` |
| `MOD(a, b)` | `a % b` |
| `POWER(base, exp)` | `POWER(base, exp)` |

### 7.7 Text functions

| Function | SQL (DuckDB) |
|---|---|
| `CONCATENATE(a, b)` | `a \|\| b` |
| `LEFT(text, n)` | `LEFT(text, n)` |
| `RIGHT(text, n)` | `RIGHT(text, n)` |
| `MID(text, start, len)` | `SUBSTRING(text, start, len)` |
| `UPPER(text)` | `UPPER(text)` |
| `LOWER(text)` | `LOWER(text)` |
| `LEN(text)` | `LENGTH(text)` |
| `FORMAT(value, fmt)` | Client-side formatting; not compiled to SQL |

### 7.8 Date functions

| Function | SQL (DuckDB) |
|---|---|
| `YEAR(date)` | `EXTRACT(YEAR FROM date)` |
| `MONTH(date)` | `EXTRACT(MONTH FROM date)` |
| `DAY(date)` | `EXTRACT(DAY FROM date)` |
| `TODAY()` | `CURRENT_DATE` |
| `DATE(y, m, d)` | `MAKE_DATE(y, m, d)` |
| `DATEDIFF(start, end, interval)` | `DATEDIFF(interval, start, end)` |
| `EOMONTH(date, offset)` | `LAST_DAY(date + INTERVAL (offset) MONTH)` |
| `WEEKDAY(date)` | `DAYOFWEEK(date)` |

### 7.9 Relationship function

| Function | Signature | Compilation |
|---|---|---|
| `RELATED(T[c])` | Looks up a value from the one side of a relationship | Compiled as a `JOIN` + column reference. Only valid in row context (calculated columns, iterators) |

### 7.10 Time intelligence (§8 has the full treatment)

| Function | What it does |
|---|---|
| `TOTALYTD(expr, dateCol)` | Year-to-date |
| `TOTALQTD(expr, dateCol)` | Quarter-to-date |
| `TOTALMTD(expr, dateCol)` | Month-to-date |
| `DATESYTD(dateCol)` | Returns the set of dates from Jan 1 to the latest date in context |
| `SAMEPERIODLASTYEAR(dateCol)` | Shifts the date filter back one year |
| `DATEADD(dateCol, n, interval)` | Shifts the date filter by n intervals |
| `PREVIOUSMONTH(dateCol)` | The complete previous month |
| `PREVIOUSYEAR(dateCol)` | The complete previous year |
| `PARALLELPERIOD(dateCol, n, interval)` | Complete periods shifted by n |

---

## 8. Time intelligence

Time intelligence functions are the second-hardest part of DAX (after CALCULATE)
and the feature users reach for most after basic aggregates.

### 8.1 Requirements

- The model must have a **date table** marked with `isDateTable: true`.
- The date table must have **one row per day** with no gaps (the engine's date
  dimension generator guarantees this).
- The date column (`dateCol` parameter) must be the column marked as the date
  table's key and must be related to the fact table's date column.

### 8.2 How they work

All time intelligence functions are **filter modifiers for CALCULATE**. They
take the current date filter and produce a new date filter.

```dax
Trips LY = CALCULATE ( [Trips], SAMEPERIODLASTYEAR('Date'[Date]) )
```

This means:
1. Look at the current filter context's date range (e.g., `Date[Date]` is
   filtered to January 2026).
2. `SAMEPERIODLASTYEAR` shifts that range back one year → January 2025.
3. CALCULATE **replaces** the date filter with this new range.
4. `[Trips]` is evaluated under the shifted date filter.

### 8.3 Compilation to SQL

The compiler resolves time intelligence in two passes:

**Pass 1 — at query planning time:** Determine the grain of the date axis.
If the visual groups by `Date[Month]`, the planner knows each output row has a
specific month, and the shifted measure needs the corresponding shifted month.

**Pass 2 — at SQL generation:** Emit the shifted aggregate as a separate CTE
with the date predicate rewritten.

Example: `[Trips]` grouped by `Date[Month]` with `[Trips LY]` alongside it.

```sql
WITH
  trips_current AS (
    SELECT dt.Month, COUNT(*) AS trips
    FROM Trip t JOIN Date dt ON dt.Date = t.StartDate
    WHERE dt.Year = 2026
    GROUP BY dt.Month
  ),
  trips_ly AS (
    SELECT dt.Month, COUNT(*) AS trips_ly
    FROM Trip t JOIN Date dt ON dt.Date = t.StartDate
    WHERE dt.Year = 2025             -- shifted by SAMEPERIODLASTYEAR
    GROUP BY dt.Month
  )
SELECT c.Month, c.trips, p.trips_ly
FROM trips_current c
LEFT JOIN trips_ly p ON p.Month = c.Month
ORDER BY c.Month;
```

The key insight: `SAMEPERIODLASTYEAR` doesn't do anything magical — it rewrites
`Year = 2026` to `Year = 2025` (or more generally, shifts every date in the
filter range back by 365/366 days). The compiler maps the group-by column back
to the same column in the shifted CTE so the JOIN works.

### 8.4 Each function's date rewrite

| Function | Input date range | Output date range |
|---|---|---|
| `SAMEPERIODLASTYEAR(d)` | [start, end] | [start − 1 year, end − 1 year] |
| `DATEADD(d, -3, MONTH)` | [start, end] | [start − 3 months, end − 3 months] |
| `PREVIOUSMONTH(d)` | any | [first day of previous month, last day of previous month] |
| `PREVIOUSYEAR(d)` | any | [Jan 1 of previous year, Dec 31 of previous year] |
| `PARALLELPERIOD(d, -1, QUARTER)` | any | [first day of prev quarter, last day of prev quarter] |
| `TOTALYTD(expr, d)` | [start, end] | [Jan 1 of end's year, end] |
| `TOTALQTD(expr, d)` | [start, end] | [first day of end's quarter, end] |
| `TOTALMTD(expr, d)` | [start, end] | [first day of end's month, end] |
| `DATESYTD(d)` | same as TOTALYTD | same — returns the dates, not the value |

For `TOTALYTD`, the "end" is the **latest date in the current context**. So if
a visual cell represents March 2026, `TOTALYTD` evaluates from January 1, 2026
through March 31, 2026.

### 8.5 Fiscal year support

`TOTALYTD` accepts an optional third argument: the fiscal year-end date as a
string `"MM/DD"`. For example, `TOTALYTD([Revenue], 'Date'[Date], "06/30")`
makes July 1 the start of the fiscal year. The compiler adjusts the start date
of the YTD range accordingly.

---

## 9. Compilation to SQL

### 9.1 The pipeline

```
DAX-lite text
  │
  ▼ lexer
Tokens
  │
  ▼ parser (Pratt, ~600 lines)
AST (abstract syntax tree)
  │
  ▼ binder
Bound AST
  - every column resolved to (table, column, type)
  - every measure resolved to its definition
  - every function resolved to its handler
  - relationships resolved
  - circular references detected
  │
  ▼ type checker
Typed AST
  - every node has a type (integer, decimal, string, date, boolean, table, blank)
  - type errors reported with position
  │
  ▼ IR lowering
Intermediate representation (IR)
  - tree of: Aggregate, Filter, Scan, Join, Project, Window
  - each Aggregate has its filter context explicitly attached
  - CALCULATE is resolved: filter replacements are applied
  - context transition is resolved: row context → filter predicates
  - time intelligence is resolved: date range rewrites
  │
  ▼ SQL generation (sqlglot)
SQL expression tree
  - one tree per (home table, filter context) pair → one sub-query
  - sub-queries JOINed on the groupBy columns
  - scalar expressions (DIVIDE, IF, SWITCH) in the outer SELECT
  │
  ▼ dialect transpile (sqlglot)
DuckDB SQL  or  T-SQL  or  PostgreSQL
```

### 9.2 How a measure becomes a sub-query

A measure like:

```dax
Completion % = DIVIDE (
    CALCULATE ( COUNTROWS(Trip), Trip[Status] = "Completed" ),
    COUNTROWS(Trip)
)
```

Under filter context `{ Date[Year] = 2026 }`, grouped by `Directorate[Name]`:

**Step 1 — identify aggregate leaves:**
- Leaf A: `COUNTROWS(Trip)` under `{ Date[Year] = 2026, Trip[Status] = "Completed" }`
- Leaf B: `COUNTROWS(Trip)` under `{ Date[Year] = 2026 }`

**Step 2 — same home table, different context → merge into one sub-query using FILTER:**

```sql
SELECT d.Name AS "Directorate[Name]",
       COUNT(*)                                         AS "__leaf_b",
       COUNT(*) FILTER (WHERE t.Status = 'Completed')  AS "__leaf_a"
FROM Trip t
  JOIN Directorate d ON d.DepartmentGuid = t.DepartmentGuid
  JOIN Date dt ON dt.Date = t.StartDate
WHERE dt.Year = 2026
GROUP BY d.Name
```

**Step 3 — scalar expressions on top:**

```sql
SELECT "Directorate[Name]",
       __leaf_a / NULLIF(__leaf_b, 0) AS "Completion %"
FROM (sub-query above)
```

### 9.3 Multi-fact measures (fan-out prevention)

If a dashboard has measures from both `Trip` and `ServiceRequest` (different
fact tables), the compiler emits **separate sub-queries per fact table** and
combines them with `FULL OUTER JOIN` on the groupBy columns.

This is the **chasm trap** prevention: joining two fact tables directly would
multiply rows. Power BI avoids this with `SUMMARIZECOLUMNS` internally; we do
it explicitly.

```sql
WITH
  trip_agg AS (
    SELECT d.Name, COUNT(*) AS trips
    FROM Trip t JOIN Directorate d ON … JOIN Date dt ON …
    WHERE dt.Year = 2026
    GROUP BY d.Name
  ),
  sr_agg AS (
    SELECT d.Name, COUNT(*) AS requests
    FROM ServiceRequest sr JOIN Directorate d ON … JOIN Date dt ON …
    WHERE dt.Year = 2026
    GROUP BY d.Name
  )
SELECT COALESCE(t.Name, s.Name) AS "Directorate[Name]",
       t.trips, s.requests
FROM trip_agg t
FULL OUTER JOIN sr_agg s ON s.Name = t.Name;
```

### 9.4 Relationship JOIN generation

The compiler builds JOINs by walking the **relationship graph** from the
fact table to each dimension table needed by groupBy, filters and measures:

1. For each column reference in the query, find its table.
2. If the table is not the fact table, find a path of relationships from the
   fact to that table (many → one direction).
3. Each relationship becomes a `JOIN`: `JOIN DimTable d ON fact.FK = d.PK`.
4. If no path exists → error: "Column X cannot be used with measure Y because
   there is no relationship path."
5. If multiple paths exist → error unless one is marked `active: true`.
   Inactive relationships can be activated with `USERELATIONSHIP` (phase 3).

### 9.5 Security predicates

RLS filters (§architecture doc, §9) are injected into **every sub-query** as
additional WHERE clauses. They are applied **after** all CALCULATE filter
replacements, so a measure with `ALL(Directorate)` removes the visual's
directorate filter but **does not remove the security filter**. This matches
Power BI's RLS semantics.

Implementation: the compiler receives a `SecurityContext` alongside the filter
context. Security predicates are held separately and are never removable by
`ALL` or `REMOVEFILTERS`.

---

## 10. BLANK semantics

DAX's BLANK is mapped to SQL's NULL, with these rules:

| DAX behaviour | SQL mapping | Notes |
|---|---|---|
| `BLANK()` | `NULL` | |
| `BLANK + 5` → `5` | `COALESCE(x, 0) + 5` | DAX treats BLANK as 0 in arithmetic |
| `BLANK & "text"` → `"text"` | `COALESCE(x, '') \|\| 'text'` | DAX treats BLANK as empty string in concatenation |
| `BLANK = BLANK` → `TRUE` | `x IS NULL AND y IS NULL` | DAX compares BLANK equal to BLANK |
| `BLANK = 0` → `TRUE` | `(x IS NULL OR x = 0) AND 0 = 0` | DAX treats BLANK as equal to 0 |
| `BLANK > 0` → `FALSE` | Standard NULL comparison after COALESCE | |
| `IF(ISBLANK(x), …)` | `IF(x IS NULL, …)` | |

**The most important BLANK rule for totals:** A measure that evaluates to NULL
(BLANK) for every groupBy combination in a row causes that row to be dropped
from the visual. This is auto-exist / blank-row removal (§11).

### 10.1 Arithmetic BLANK propagation

DAX-lite follows DAX's rule: BLANK in arithmetic is treated as 0 (not as NULL
propagation). The compiler wraps column references in aggregates with
`COALESCE(col, 0)` when the measure's expression uses arithmetic:

```dax
Revenue = SUMX(Order, Order[Qty] * Order[Price])
```

```sql
SUM(COALESCE(o.Qty, 0) * COALESCE(o.Price, 0))
```

This ensures that a NULL Qty row contributes 0 to the sum rather than making
the entire SUM null.

### 10.2 Where we differ from DAX

`BLANK = 0` returning TRUE is the most surprising DAX behaviour and the hardest
to implement in SQL without wrapping every comparison. DAX-lite matches this
behaviour for `IF`/`SWITCH` conditions involving measures (where it matters
for dashboard logic), but uses standard SQL NULL semantics in filter predicates.
A golden test suite (§15) pins down every edge case.

---

## 11. Auto-exist and blank-row removal

### 11.1 Blank-row removal

After the query runs, rows where **every measure is NULL** are dropped from the
result before returning it to the visual. This matches Power BI's
`SUMMARIZECOLUMNS` behaviour.

```sql
-- Applied as a final WHERE clause (or HAVING) on the outer query:
WHERE NOT (measure_1 IS NULL AND measure_2 IS NULL AND … AND measure_n IS NULL)
```

This is why Power BI visuals never show cartesian-product rows that have no
data — and why a dimension value disappears when its fact table has no matching
rows.

### 11.2 Auto-exist

Auto-exist applies when two or more groupBy columns come from the **same
dimension table**: only combinations that actually exist in that table are
returned. For example, grouping by `Directorate[Region]` and
`Directorate[Name]` returns only (Region, Name) pairs that exist in the
Directorate table, not all possible combinations.

In SQL this is natural: the columns come from the same joined table, so only
existing combinations appear. Auto-exist is "free" in our compilation model.
(In DAX's internal engine it is an optimisation that avoids materialising the
cross product; in SQL, it's just a GROUP BY over joined columns.)

### 11.3 IGNORE (not in MVP)

DAX's `SUMMARIZECOLUMNS` supports an `IGNORE()` wrapper that exempts a measure
from the blank-row check. We omit this in the MVP. If needed later, it maps to
excluding that measure from the `WHERE NOT (… IS NULL …)` clause.

---

## 12. Totals and subtotals

Totals are **not the sum of the visible rows.** They are the measure
re-evaluated at the coarser grain. This is critical for ratios, averages and
distinct counts.

### 12.1 Example

| Directorate | Trips | Completion % |
|---|---|---|
| Operations | 412 | 93% |
| Logistics | 301 | 88% |
| **Total** | **713** | **91%** |

- `Trips` total: 412 + 301 = 713 ✓ (additive)
- `Completion %` total: NOT (93% + 88%) / 2 = 90.5%. It is
  `DIVIDE(CompletedTrips_total, Trips_total)` = `DIVIDE(649, 713)` = 91%.
  The measure is re-evaluated without the Directorate grouping.

### 12.2 Compilation

**Additive measures** (SUM, COUNT, COUNTROWS): the planner uses
`GROUPING SETS` to compute the detail rows and the total in one query:

```sql
SELECT d.Name, COUNT(*) AS trips
FROM Trip t JOIN Directorate d ON …
WHERE dt.Year = 2026
GROUP BY GROUPING SETS ((d.Name), ())
```

The `()` grouping set is the grand total.

**Non-additive measures** (DIVIDE, AVERAGE, DISTINCTCOUNT, any expression):
the planner emits a **separate query** for the total row, removing the groupBy
column from the GROUP BY and re-computing the measure. This is more expensive
but correct.

Subtotals (for matrix visuals with nested row grouping) follow the same
pattern: one grouping set per subtotal level for additive measures; separate
queries for non-additive ones.

### 12.3 When totals differ between DAX and SQL

| Case | DAX | DAX-lite (SQL) | Notes |
|---|---|---|---|
| `SUM` total | Sum of detail values | Same (`GROUPING SETS`) | Identical |
| `AVERAGE` total | Average of all rows, not average of averages | Same (separate query at coarser grain) | Identical |
| `DISTINCTCOUNT` total | Distinct count across all rows | Same | Identical |
| `DIVIDE` total | Re-evaluated ratio | Same | Identical |
| Measure with `ALL` in denominator | ALL scope changes with the grain | Same — `ALL` removes groupBy columns, so the denominator is the same at detail and total | Identical |

---

## 13. Error model

### 13.1 Compile-time errors (at model save)

| Error | Example | Message |
|---|---|---|
| Unknown function | `ADDCOLUMNS(…)` | `ADDCOLUMNS is a DAX function not supported in DAX-lite. Consider creating a SQL view for complex table expressions.` |
| Unknown identifier | `Tripp[Status]` | `Table 'Tripp' not found in model. Did you mean 'Trip'?` |
| Type mismatch | `SUM(Trip[Status])` | `SUM requires a numeric column. Trip[Status] is type string.` |
| Circular reference | `[A] = [B] + 1`, `[B] = [A] + 1` | `Circular reference: [A] → [B] → [A]` |
| No relationship path | `SUM(Trip[Dist])` grouped by `Supplier[Name]` | `No relationship path from Trip to Supplier. Add a relationship or remove the grouping.` |
| Ambiguous relationship | Two active paths from Trip to Date | `Multiple active relationships from Trip to Date. Deactivate one or use USERELATIONSHIP.` |
| Aggregation in calc column | `= SUM(Trip[Dist])` on a calc column | `Calculated columns cannot contain aggregations. Use a measure instead.` |
| Missing aggregation in measure | `= Trip[Dist] + 1` in a measure | `Measures must aggregate. Did you mean SUM(Trip[Dist]) + 1?` |

### 13.2 Runtime errors

| Error | Handling |
|---|---|
| Division by zero | `DIVIDE` returns BLANK (NULL); raw `/` returns NULL via `NULLIF` |
| Overflow | DuckDB's native overflow behaviour (error or wrap); caught and reported |
| Type conversion failure | `CAST` failure → NULL + warning in query response |

### 13.3 Editor experience

The formula editor (Monaco with a DAX-lite language mode) shows:
- **Red squiggles** on errors, with the message on hover.
- **Autocomplete** for table names, column names, measure names and function
  names (from the binder).
- **Signature help** for function arguments.
- **Semantic highlighting**: functions in blue, tables in purple, columns in
  teal, measures in orange, strings in green, numbers in coral.
- A **"Compiles to"** panel showing the generated SQL for the current measure,
  similar to Power BI's Performance Analyzer → "copy query" feature.

---

## 14. What is deliberately excluded

| DAX feature | Why excluded | Alternative |
|---|---|---|
| **Table expressions in measures** (`ADDCOLUMNS`, `SUMMARIZE`, `GENERATE`, `TOPN`, `UNION`, `EXCEPT`, `INTERSECT`, `DATATABLE`, `CALENDAR`) | Each is an entire SQL query builder. Supporting them makes the compiler unbounded. | Create a SQL view in the source database, or a prep recipe step |
| **`EARLIER`** | Confusing even in DAX; `VAR` replaced it years ago | Use `VAR` |
| **Calculation groups** | Complex metadata feature; equivalent to parameterised measures | Define separate measures |
| **Many-to-many relationships** | Requires bridge table logic; deferred to phase 3 | Model it as a bridge table with two many-to-one relationships |
| **Bidirectional cross-filter** | Can cause ambiguous results and performance problems | Deferred; model as explicit filters or bridge tables |
| **`USERELATIONSHIP`** | Deferred to phase 3 | Use only one active relationship per pair |
| **`CONCATENATEX`** | String aggregation is rare and expensive | `STRING_AGG` via a custom SQL measure if needed |
| **`RANKX`, `PERCENTILEX`** | Window-function measures; deferred to phase 3 | Use the query engine's sort + limit |
| **Dynamic format strings** | Complex UI feature | Fixed format per measure |
| **Object-level security (OLS)** | Column-level hiding; deferred | Omit columns from the model |

### 14.1 How unsupported functions are handled

The parser maintains a list of all ~350 DAX function names. When it encounters
one not in the supported set, it produces a **specific error**, not a generic
"unexpected token":

```
Error at line 2, column 12:
  TOPN is a DAX function not supported in DAX-lite.
  Consider creating a SQL view that computes the top-N rows,
  and importing it as a table in your model.
```

Unknown identifiers that don't match any DAX function name get:

```
Error at line 2, column 12:
  Unknown function 'MYTHING'. Check the spelling, or see the
  function reference for the list of supported functions.
```

---

## 15. Golden tests

Every function and every semantic edge case has a **golden test**: a small,
fixed dataset, a measure, an expected result, and the generated SQL.

### 15.1 Test structure

```yaml
# tests/formula/golden/calculate_replace.yaml
name: CALCULATE replaces filter on the same column
dataset:
  tables:
    - name: Sales
      rows:
        - { Region: "East", Year: 2025, Amount: 100 }
        - { Region: "East", Year: 2026, Amount: 200 }
        - { Region: "West", Year: 2025, Amount: 150 }
        - { Region: "West", Year: 2026, Amount: 250 }
    - name: Date
      rows:
        - { Year: 2025 }
        - { Year: 2026 }
  relationships:
    - Sales.Year -> Date.Year

measures:
  Total: "SUM(Sales[Amount])"
  Prior Year: "CALCULATE([Total], Date[Year] = 2025)"

query:
  groupBy: ["Sales[Region]"]
  measures: ["[Total]", "[Prior Year]"]
  filters: [{ column: "Date[Year]", op: "=", value: 2026 }]

expected:
  columns: ["Sales[Region]", "[Total]", "[Prior Year]"]
  rows:
    - ["East", 200, 100]
    - ["West", 250, 150]
  totals: [null, 450, 250]

expected_sql_contains:
  - "FILTER (WHERE"       # the Status filter on the same aggregate
  # or, for a separate CTE approach:
  - "dt.Year = 2025"      # the replaced filter
```

### 15.2 Categories of golden tests

| Category | Count (est.) | What they pin down |
|---|---|---|
| Basic aggregations (SUM, COUNT, etc.) | ~20 | NULL handling, empty tables, type edge cases |
| CALCULATE — filter replacement | ~15 | Single column, multiple columns, multiple arguments |
| CALCULATE — KEEPFILTERS | ~5 | Intersection vs replacement |
| CALCULATE — ALL / ALLEXCEPT | ~10 | Remove one column, all columns, all except |
| CALCULATE — nested | ~5 | Inner/outer context interaction |
| Context transition | ~8 | SUMX + measure ref, SUMX + RELATED |
| Time intelligence | ~15 | SAMEPERIODLASTYEAR, DATEADD, TOTALYTD (monthly, quarterly, YTD at year boundary, fiscal year) |
| BLANK semantics | ~10 | BLANK + number, BLANK in comparison, BLANK in IF, BLANK row removal |
| Totals | ~10 | Additive, non-additive (DIVIDE, AVERAGE, DISTINCTCOUNT), ALL in denominator |
| Multi-fact | ~5 | Two fact tables, FULL OUTER JOIN, no fan-out |
| RLS | ~5 | Security filter not removable by ALL |
| Error cases | ~15 | Every error in §13 |
| **Total** | **~125** | |

### 15.3 Parity tests

A separate suite compares v2 results against Power BI for every published MSD
measure. The test loads the same data into DuckDB and into a Power BI semantic
model, runs the same semantic query against both, and asserts that every cell
matches within a tolerance of 0.01 (for floating-point rounding).

```yaml
# tests/parity/transport/fleet_availability.yaml
module: transport
dashboard: fleet-availability
source: MSD_ERP  # or a snapshot
measures:
  - "[Active vehicles]"
  - "[Trips]"
  - "[Completion %]"
  - "[Trips prev month]"
  - "[Km per litre]"
groupBy: ["Directorate[Name]", "Date[Month]"]
filters: [{ column: "Date[Year]", op: "=", value: 2026 }]
tolerance: 0.01
```

---

## 16. Appendix: grammar in EBNF

```ebnf
program         = measure_def | calc_column_def ;

measure_def     = identifier "=" expression ;
calc_column_def = table_ref "[" identifier "]" "=" expression ;

expression      = var_block | or_expr ;

var_block       = "VAR" identifier "=" expression
                  { "VAR" identifier "=" expression }
                  "RETURN" expression ;

or_expr         = and_expr { ("OR" | "||") and_expr } ;
and_expr        = not_expr { ("AND" | "&&") not_expr } ;
not_expr        = "NOT" not_expr | comparison ;
comparison      = add_expr [ comp_op add_expr ]
                | add_expr "IN" set_literal ;
comp_op         = "=" | "<>" | "<" | ">" | "<=" | ">=" ;
add_expr        = mul_expr { ("+" | "-") mul_expr } ;
mul_expr        = unary { ("*" | "/") unary } ;
unary           = "-" unary | primary ;

primary         = number
                | string
                | "TRUE" | "FALSE"
                | "BLANK" "(" ")"
                | column_ref                          (* Table[Column] *)
                | measure_ref                         (* [Measure] *)
                | function_call
                | "(" expression ")" ;

function_call   = identifier "(" [ arg_list ] ")" ;
arg_list        = expression { "," expression } ;

column_ref      = table_ref "[" identifier "]" ;
measure_ref     = "[" identifier "]" ;
table_ref       = identifier | "'" identifier "'" ;

set_literal     = "{" expression { "," expression } "}" ;

identifier      = letter { letter | digit | " " | "_" } ;
number          = digit { digit } [ "." digit { digit } ] [ ("e"|"E") ["+"|"-"] digit { digit } ] ;
string          = '"' { char | '""' } '"' ;
```

The parser is a hand-written **Pratt parser** (~600 lines of TypeScript or
Python), not a generated one. Pratt parsers handle operator precedence
naturally, give excellent error messages with position information, and are
easy to extend with new prefix/infix operators. The lexer is a simple
state machine (~200 lines).

---

## Summary: what this spec pins down

| Question | Answer |
|---|---|
| What can a user write? | DAX syntax, ~40 functions, no table expressions in measures |
| What happens when CALCULATE runs? | §5.2 — evaluate filters against outer context, then replace |
| What happens inside SUMX? | §6 — row context; measure refs trigger context transition |
| How do time functions work? | §8 — date range rewrite, compiled as shifted CTEs |
| What is BLANK? | §10 — NULL, but 0 in arithmetic and equal to 0 in comparisons |
| Why do rows disappear? | §11 — blank-row removal (all measures NULL → row dropped) |
| Why don't totals match row sums? | §12 — totals re-evaluate at coarser grain |
| What if I write unsupported DAX? | §14 — named error with a suggested alternative |
| How do we know it's correct? | §15 — ~125 golden tests + parity suite against Power BI |

This is the document the engine team implements against. If a behaviour isn't
specified here, it is undefined in v2 — which means we should either add it
to this spec or decide it's out of scope.
