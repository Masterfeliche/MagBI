# 05 — DAX-lite Formula Language

> **Status: Implemented for one measure at a time (MAGBI-004).**
>
> The compiler turns one formula into one DuckDB `SELECT`. T-SQL and DirectQuery are not emitted yet.
>
> **Supported now:** `SUM`, `COUNT`, `COUNTA`, `COUNTROWS`, `AVERAGE`, `MIN`, `MAX`, `DISTINCTCOUNT`, `DIVIDE`, `IF`, `CALCULATE`, `ALL`, `REMOVEFILTERS`, `FILTER`, `AND`, `OR`, `NOT`, `TRUE`, `FALSE`, `BLANK`, `ISBLANK`, `SAMEPERIODLASTYEAR`, `DATEADD`, `TOTALYTD`, plus `+ - * / = <> < > <= >= && || &`, `IN { … }`, parentheses, and `VAR` / `RETURN`.
>
> **Later:** iterators (`SUMX` and the other X functions), `RELATED`, `KEEPFILTERS`, `ALLEXCEPT`, `VALUES`, `SWITCH`, the visual query (group-by, totals, multi-fact joins, blank-row removal), row-level security, the Monaco editor, and T-SQL.

---

## What It Does

DAX-lite is MagBI's formula language. It lets users define **measures** — named
calculations that aggregate data differently depending on what the user is
looking at. A measure like `Revenue = SUM(Sales[Amount])` returns total revenue
when the chart shows one bar, revenue per month when the chart groups by month,
and revenue per customer when the chart groups by customer.

SQL can do aggregation too, but DAX-lite exists because some very common BI
calculations are awkward or impossible to express in a single SQL query:

| Calculation | SQL | DAX-lite |
|------------|-----|---------|
| Revenue this year vs. last year | Two subqueries UNIONed or a self-join with date arithmetic | `CALCULATE(SUM(Sales[Amount]), SAMEPERIODLASTYEAR(Date[Date]))` |
| Each product's share of total | Window function or subquery for grand total | `DIVIDE(SUM(Sales[Amount]), CALCULATE(SUM(Sales[Amount]), ALL(Product)))` |
| Running total by month | `SUM() OVER (ORDER BY ...)` — but only if the database supports window functions in this context | `CALCULATE(SUM(Sales[Amount]), FILTER(ALL(Date), Date[Date] <= MAX(Date[Date])))` |
| Conditional aggregation with context manipulation | Deeply nested CASE/subquery | `CALCULATE(COUNTROWS(Sales), Sales[Status] = "Active")` |

DAX-lite uses the same syntax as Microsoft's DAX (Data Analysis Expressions),
used in Power BI, Analysis Services, and Excel Power Pivot. This is a deliberate
choice — millions of Power BI users already know DAX, and the body of tutorials,
books, and community knowledge is enormous.

**What "lite" means:** MagBI implements ~40 of DAX's ~250+ functions. We cover
the functions that appear in 95% of real-world measures and skip the exotic
ones (SUMMARIZE with expressions, GENERATE, CROSSJOIN, PATH functions). If a
formula uses an unsupported function, the compiler returns a clear error.

---

## Why This Approach

### DAX syntax, not a custom DSL

We could have invented our own formula syntax. We chose DAX because:

1. **Familiarity.** Our first customer (MSD ERP) already uses Power BI. Their
   analysts know DAX. Zero learning curve for measures they already wrote.
2. **Community.** "How to calculate year-over-year in DAX" returns thousands of
   results. "How to calculate year-over-year in MagBI-formula-v1" returns zero.
3. **Precision.** DAX semantics are well-documented by Microsoft and deeply
   analysed by the community (Marco Russo, Alberto Ferrari, SQLBI). We do not
   have to invent semantics; we implement documented behaviour.

**Trade-off:** We inherit DAX's complexity. CALCULATE's filter replacement
semantics are notoriously confusing. But better to be compatible with a known
system than to invent a simpler system that nobody knows.

### Compile to SQL, not interpret

Some BI tools interpret formulas row-by-row in their own engine. Power BI's
VertiPaq engine stores data in columnar format and executes DAX natively.

MagBI compiles DAX-lite to SQL and executes it on DuckDB. This means:

- **Performance comes from DuckDB**, not from us writing a high-performance
  evaluation engine. DuckDB is written in C++ by database researchers; we would
  not beat it in Python.
- **Portability.** The same measure can run on DuckDB (imported data) or be
  transpiled to T-SQL/PostgreSQL for DirectQuery. sqlglot handles dialect
  differences.
- **Debuggability.** When a measure returns wrong results, we can inspect the
  generated SQL. SQL is a well-understood language; custom engine internals are
  opaque.

**Trade-off:** Not every DAX concept maps cleanly to SQL. Context transition
(see below) generates correlated subqueries. Some measures produce complex
nested SQL that is less efficient than a native DAX engine would be.

---

## How It Works

### The compilation pipeline

```
DAX text → Lexer → Tokens → Parser → AST → Binder → Bound AST
    → Type Checker → Typed AST → Compiler → sqlglot IR → SQL
```

Each stage has a clear input and output. If any stage fails, it returns a
descriptive error with the position in the formula.

### Stage 1: Lexer (Tokenizer)

The lexer reads the DAX text character by character and produces a stream of
tokens:

```
SUM(Sales[Amount]) + 100
```

becomes:

```
FUNCTION("SUM"), LPAREN, TABLE_COLUMN("Sales", "Amount"), RPAREN,
PLUS, INTEGER(100)
```

**Key lexer decisions:**

- **Table[Column] syntax** is tokenised as a single `TABLE_COLUMN` token. The
  lexer recognises the `TableName[ColumnName]` pattern and captures both parts.
- **String literals** use double quotes: `"Active"`. Single quotes are not used
  (unlike SQL).
- **Keywords** (`CALCULATE`, `IF`, `VAR`, `RETURN`, `TRUE`, `FALSE`, `BLANK`)
  are case-insensitive. `calculate` and `CALCULATE` produce the same token.

### Stage 2: Pratt Parser

The parser converts the token stream into an Abstract Syntax Tree (AST).

**Why Pratt parsing (not recursive descent or parser generators):**

A **recursive-descent parser** uses one function per grammar rule. For
expressions with multiple precedence levels (addition < multiplication < unary
minus < function call), you need many levels of mutual recursion. Parsing
`a + b * c - d` correctly requires getting the precedence right in the function
structure, and adding a new operator means restructuring the call chain.

A **parser generator** (ANTLR, PEG, Lark) takes a grammar file and generates
a parser. This is powerful but heavyweight — it adds a build step, generates
hard-to-debug code, and the grammar file is another language to learn.

A **Pratt parser** (also called "top-down operator precedence") assigns a
binding power to each operator and uses a single loop to build the tree. Adding
a new operator is one line: `register_infix(PLUS, binding_power=10, ...)`.
Pratt parsers are:

- Simple: ~100 lines of code for the core loop
- Correct: naturally handle all precedence levels
- Extensible: adding operators/functions does not change the core
- Fast: single pass, no backtracking

The core algorithm:

```python
def parse_expression(min_bp=0):
    # Handle prefix (unary minus, NOT, parentheses)
    left = parse_prefix()

    while True:
        # Peek at the next operator
        op = peek()
        bp = binding_power(op)

        # If the operator binds less tightly, stop
        if bp < min_bp:
            break

        advance()  # consume the operator

        # Parse the right side with higher minimum binding power
        right = parse_expression(bp + 1)  # +1 for left-associativity
        left = BinaryExpr(op, left, right)

    return left
```

This 15-line loop handles all of: arithmetic (`+ - * /`), comparison
(`= <> > < >= <=`), logical (`&& ||`), string concatenation (`&`), and
unary minus — with correct precedence and associativity.

### Stage 3: Binder

The binder resolves names in the AST against the semantic model:

- `Sales[Amount]` → resolves to column `Amount` in table `Sales`
- `[Revenue]` → resolves to measure `Revenue` in the current table
- `SUM` → resolves to the built-in aggregation function

If a name cannot be resolved, the binder reports an error: "Column 'Ammount'
not found in table 'Sales'. Did you mean 'Amount'?"

### Stage 4: Compiler (AST → sqlglot IR → SQL)

The compiler walks the typed AST and produces a sqlglot expression tree:

```
DAX: SUM(Sales[Amount])
 →  sqlglot: exp.Sum(this=exp.Column(table="Sales", this="Amount"))
 →  SQL: SUM("Sales"."Amount")
```

For simple aggregations, this is straightforward. For CALCULATE with filter
arguments, the compiler must understand the two evaluation contexts.

---

## The Two Evaluation Contexts

This is the most important concept in DAX, and the source of most confusion.
Understanding it deeply is worth the investment.

### Row context

A **row context** means "the formula is being evaluated for a specific row."
This happens in:

- Calculated columns (one row at a time)
- Iterator functions like `SUMX(Sales, Sales[Qty] * Sales[Price])` — the inner
  expression `Sales[Qty] * Sales[Price]` runs once per row

In row context, `Sales[Qty]` refers to the value of `Qty` in *this* row.

### Filter context

A **filter context** is a set of active filters that restrict which rows are
visible. This happens in:

- Every cell of a chart (the chart's grouping creates a filter)
- When the user applies a slicer or cross-filter

In filter context, `SUM(Sales[Amount])` sums *only* the rows that pass all
active filters.

**Example:** A bar chart groups by `Product[Category]`. For the "Electronics"
bar, the filter context is `Product[Category] = "Electronics"`. The measure
`SUM(Sales[Amount])` sums only sales of electronics products.

### Context transition

When a row context encounters a measure reference, the row context is
**transitioned** into a filter context. This sounds abstract but is concretely
powerful:

```dax
Revenue = SUM(Sales[Amount])

RevenueRank =
    RANKX(
        ALL(Product),
        [Revenue]  // ← this triggers context transition
    )
```

`RANKX` iterates over all products (row context). For each product, `[Revenue]`
is a measure, so the row context (current product) transitions into a filter
context (`Product[ProductID] = <this row's ProductID>`). The measure then sums
only that product's sales.

**How MagBI compiles context transition:** The compiler generates a correlated
subquery:

```sql
-- RevenueRank
RANK() OVER (
    ORDER BY (
        SELECT SUM(Sales.Amount)
        FROM Sales
        JOIN Product ON Sales.ProductID = Product.ProductID
        WHERE Product.ProductID = outer.ProductID  -- context transition
    ) DESC
)
```

---

## CALCULATE — The Heart of DAX

`CALCULATE` is the only function that can **modify the filter context**. Every
other function reads the filter context; CALCULATE changes it.

```dax
CALCULATE(SUM(Sales[Amount]), Product[Category] = "Electronics")
```

This says: "Take the current filter context, add/replace the filter
`Product[Category] = 'Electronics'`, then evaluate `SUM(Sales[Amount])` in the
modified context."

### The 5-step algorithm

When MagBI encounters CALCULATE:

1. **Evaluate filter arguments** in the *outer* filter context (before
   modification)
2. **Copy** the current filter context
3. **Apply context transition** if there is a row context (convert row values
   to filters)
4. **Apply filter arguments** — by default, each filter **replaces** existing
   filters on the same column. (`Product[Category] = "Electronics"` removes any
   existing filter on `Product[Category]`)
5. **Evaluate the first argument** (the expression) in the modified filter
   context

### KEEPFILTERS — intersect instead of replace

By default, CALCULATE replaces filters. `KEEPFILTERS` changes this to
intersection:

```dax
// Without KEEPFILTERS: shows Electronics revenue even if user filtered to "Shoes"
CALCULATE(SUM(Sales[Amount]), Product[Category] = "Electronics")

// With KEEPFILTERS: shows Electronics only if user also selected it
CALCULATE(SUM(Sales[Amount]), KEEPFILTERS(Product[Category] = "Electronics"))
```

### ALL — remove filters

`ALL(table)` or `ALL(column)` removes filters from the specified scope:

```dax
// Share of total: divide by unfiltered total
DIVIDE(
    SUM(Sales[Amount]),
    CALCULATE(SUM(Sales[Amount]), ALL(Product))
)
```

`ALL(Product)` removes all filters on the Product table, so the denominator is
the grand total regardless of which product the user selected.

**RLS exception:** ALL can remove user filters but **never** RLS filters. This
is enforced at the SQL level — RLS filters are injected in a separate WHERE
clause that ALL does not touch.

---

## Function Categories

### Aggregation (~10 functions)
`SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `COUNTA`, `COUNTROWS`,
`DISTINCTCOUNT`, `COUNTBLANK`

These collapse rows into a single value. They respect the current filter context.

### Iterator (~5 functions)
`SUMX`, `AVERAGEX`, `MINX`, `MAXX`, `COUNTX`

These iterate over a table expression and evaluate a row expression for each
row, then aggregate the results. `SUMX(Sales, Sales[Qty] * Sales[Price])`
computes the product per row, then sums.

### Filter manipulation (~8 functions)
`CALCULATE`, `ALL`, `ALLEXCEPT`, `REMOVEFILTERS`, `KEEPFILTERS`, `FILTER`,
`VALUES`, `SELECTEDVALUE`

These modify or inspect the filter context. CALCULATE is the most complex; the
others are simpler utilities.

### Logic (~5 functions)
`IF`, `SWITCH`, `AND`, `OR`, `NOT`

Conditional logic. `IF` and `SWITCH` are by far the most used.

### Time intelligence (~8 functions)
`SAMEPERIODLASTYEAR`, `DATEADD`, `DATESYTD`, `DATESQTD`, `DATESMTD`,
`TOTALYTD`, `TOTALQTD`, `TOTALMTD`

These manipulate date ranges. `SAMEPERIODLASTYEAR(Date[Date])` shifts the
current date filter back by one year.

**How time intelligence compiles:** The compiler rewrites time functions as
date-range filters. `SAMEPERIODLASTYEAR(Date[Date])` becomes:

```sql
WHERE Date.Date BETWEEN
    DATEADD(YEAR, -1, <current_min_date>)
    AND DATEADD(YEAR, -1, <current_max_date>)
```

This requires a contiguous date table (chapter 04) to determine the current
date range.

### Math / Text / Utility (~10 functions)
`DIVIDE`, `ROUND`, `ABS`, `CONCATENATE`, `FORMAT`, `BLANK`, `ISBLANK`,
`VAR` / `RETURN`, `HASONEVALUE`

`DIVIDE` is notable: `DIVIDE(a, b)` returns BLANK when `b` is zero, instead
of erroring. This is the safe division function used everywhere in BI.

---

## BLANK Semantics

DAX has three-valued logic: TRUE, FALSE, and BLANK. BLANK is not NULL in the
SQL sense, but it behaves similarly:

- BLANK + 5 = BLANK (arithmetic propagation)
- BLANK = BLANK is TRUE (unlike SQL's NULL = NULL which is NULL)
- BLANK in a boolean context is FALSE
- `SUM` ignores BLANK values (like SQL's SUM ignores NULL)

MagBI compiles BLANK to SQL NULL for most operations, with special handling for
the equality case (`BLANK = BLANK → TRUE` compiles to `IS NOT DISTINCT FROM`
in DuckDB).

### Auto-exist and blank-row removal

When a chart groups by Product and shows Revenue, products with zero sales
should typically NOT appear (blank rows). MagBI removes rows where all measures
are BLANK — this is "auto-exist" or "blank-row removal."

This is implemented as a post-processing step: after the SQL query returns,
the engine filters out rows where every measure column is NULL.

---

## What We Deliberately Excluded

| Feature | Why excluded |
|---------|-------------|
| SUMMARIZE with expressions | Complex semantics, SUMMARIZECOLUMNS preferred but generates complex SQL |
| Many-to-many via TREATAS | Requires filter table materialisation; Phase 2 |
| GENERATE / CROSSJOIN | Rarely used in measures; complex to compile to SQL |
| PATH functions | Designed for parent-child hierarchies; niche use case |
| GROUPBY | Obscure alternative to SUMMARIZE; rarely used |
| Complex security filters | Multi-table RLS with calculated predicates; Phase 2 |
| USERELATIONSHIP | Inactive relationship activation; Phase 2 |
| FORMAT with arbitrary strings | Would require building a format engine; use formatString on the measure instead |

Each exclusion is marked "Phase 2" where we intend to add it later, or left
unmarked where we have no plans to support it.

---

## Strengths

- **Familiar syntax** — Power BI users write measures without relearning
- **Compiles to SQL** — DuckDB handles execution; no custom engine to maintain
- **Portable** — same measure runs on DuckDB, SQL Server, or PostgreSQL
- **Well-defined semantics** — we follow Microsoft's documented behaviour
- **Clear error messages** — the compiler reports errors with source positions

## Weaknesses & Risks

- **Not full DAX** — some Power BI measures will not work. Users must check
  the supported function list.
- **Complex SQL output** — CALCULATE with multiple filter arguments generates
  deeply nested subqueries. Some queries may be slow.
- **Context transition produces correlated subqueries** — these can be slow on
  large datasets. DuckDB handles them well, but DirectQuery sources may not.
- **Three-valued logic is confusing** — BLANK = BLANK being TRUE while SQL's
  NULL = NULL is NULL creates subtle bugs at the compilation boundary.
- **Time intelligence requires a date table** — if the user forgets to mark
  a date table, time functions fail with an obscure error.

---

## For Agents

1. DAX-lite source lives in `server/magbi/dax/` — lexer, parser, binder,
   compiler, functions.
2. The ~125 golden tests in `server/tests/test_dax/` are the specification.
   Before changing the compiler, verify all golden tests pass. After adding a
   function, add golden tests.
3. CALCULATE's 5-step algorithm is the hardest code in the system. Do not
   modify it without reading this chapter's CALCULATE section AND the
   DAX-LITE-SPEC.md architecture doc.
4. RLS filters are never removable. If you touch ALL or REMOVEFILTERS, verify
   that RLS filters survive.
5. When adding a new function, add it to `functions.py`, add golden tests, and
   update the function table in this chapter.

---

## Further Reading

- [The Definitive Guide to DAX (Marco Russo & Alberto Ferrari)](https://www.sqlbi.com/books/the-definitive-guide-to-dax/)
  — the authoritative reference; our CALCULATE semantics follow this book
- [SQLBI articles on evaluation contexts](https://www.sqlbi.com/articles/row-context-and-filter-context-in-dax/)
- [Pratt Parsing (Bob Nystrom)](https://journal.stuffwithstuff.com/2011/03/19/pratt-parsers-expression-parsing-made-easy/)
  — the best explanation of the algorithm we use
- [sqlglot expression API](https://sqlglot.com/sqlglot/expressions.html)
- [Three-valued logic in databases](https://en.wikipedia.org/wiki/Null_(SQL)#Three-valued_logic)
