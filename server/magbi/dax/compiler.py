"""Compile a measure to one DuckDB SELECT.

Aggregates on different tables are rejected. ``+`` and ``-`` treat NULL as 0.
``DIVIDE`` by zero is NULL. CALCULATE replaces filters on the columns it
mentions; ALL removes them. A table named by a filter, by RELATED, by a
context function or by ``also`` is joined on the active relationship path.

Iterators (SUMX…) aggregate a row expression over their table's rows.
SELECTEDVALUE and HASONEVALUE look at the rows in the current filter context.
RANKX is a window over the visual's rows, so it ranks what the visual shows.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass
from typing import cast

from sqlglot import exp

from magbi.dax.binder import bind_measure
from magbi.dax.errors import DaxError
from magbi.dax.functions import AGGREGATES, CONTEXT, IDENTITY, ITERATORS
from magbi.dax.parser import (
    Binary,
    BoolLit,
    Call,
    ColumnRef,
    Expr,
    InExpr,
    NameRef,
    NumberLit,
    StringLit,
    TableRef,
    Unary,
    VarBlock,
)
from magbi.model.relationships import query_path
from magbi.model.schema import DatasetDefinition, ModelSchemaError, RelationshipDef

_OPS = {"=", "<>", "<", ">", "<=", ">="}
_FLIP = {"=": "<>", "<>": "=", "<": ">=", ">": "<=", "<=": ">", ">=": "<"}


@dataclass(frozen=True, slots=True)
class AggregatePlan:
    """One measure's aggregate expression and the tables it needs joined."""

    expression: exp.Expression
    fact: str
    tables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Constraint:
    """One filter. ``columns`` are the ones a later CALCULATE argument replaces."""

    columns: tuple[tuple[str, str], ...]
    op: str
    value: object


def compile_row_expression(model: DatasetDefinition, source: str) -> exp.Expression:
    """Compile a calculated column. Aggregations are rejected by the binder."""
    from magbi.dax.binder import bind_calculated_column

    expr = bind_calculated_column(model, source)
    extra: set[str] = set()
    _extra_tables(expr, extra)
    if extra:
        raise DaxError("calculated columns can use their own table's columns only, yet", expr.line, expr.col)
    return _scalar(expr, {}, (), model)


def home_table(model: DatasetDefinition, source: str) -> str:
    """The table a measure aggregates over, found without compiling it.

    Compiling needs the filter context (time intelligence reads the date
    filter), which the engine only knows once it has the home table.
    """
    expr = bind_measure(model, source)
    facts: set[str] = set()
    _facts(expr, facts)
    if not facts:
        _context_tables(expr, facts)
    if len(facts) != 1:
        raise DaxError("measures that combine two fact tables are compiled by the query engine", expr.line, expr.col)
    return next(iter(facts))


def compile_aggregate(
    model: DatasetDefinition,
    source: str,
    *,
    filters: tuple[tuple[str, str, str, object], ...] = (),
) -> AggregatePlan:
    """Return the aggregate expression for a measure, not a full SELECT."""
    prepared = _prepare(model, source, filters)
    return AggregatePlan(prepared[1], prepared[0], prepared[2])


def compile_measure(
    model: DatasetDefinition,
    source: str,
    *,
    also: tuple[str, ...] = (),
    filters: tuple[tuple[str, str, str, object], ...] = (),
) -> str:
    """Return DuckDB SQL for a measure. ``also`` tables are joined in.

    ``filters`` is the incoming filter context, each item
    ``(table, column, operator, value)``.
    """
    fact, scalar, tables, expr = _prepare(model, source, filters)
    query: exp.Select = exp.select(scalar).from_(_table(fact))
    joined = {fact}
    extras = list(also)
    for table in tables:
        if table not in extras:
            extras.append(table)
    for extra in dict.fromkeys(extras):
        if extra in joined:
            continue
        try:
            path = query_path(model, fact, extra)
        except ModelSchemaError as exc:
            raise DaxError(str(exc), expr.line, expr.col) from None
        cursor = fact
        for rel in path:
            nxt = rel.to.table if rel.from_.table == cursor else rel.from_.table
            if nxt not in joined:
                query = query.join(_table(nxt), on=_on(rel), join_type=_join_kind(rel))
                joined.add(nxt)
            cursor = nxt
    return query.sql(dialect="duckdb")


def _prepare(
    model: DatasetDefinition,
    source: str,
    filters: tuple[tuple[str, str, str, object], ...],
) -> tuple[str, exp.Expression, tuple[str, ...], Expr]:
    expr = bind_measure(model, source)
    context = tuple(
        Constraint(((table, column),), op, value)
        for table, column, op, value in filters
    )
    facts: set[str] = set()
    _facts(expr, facts)
    if not facts:
        # Only SELECTEDVALUE or HASONEVALUE: their column's table is the home table.
        _context_tables(expr, facts)
    if len(facts) != 1:
        raise DaxError(
            "measures that combine two fact tables are compiled by the query engine",
            expr.line,
            expr.col,
        )
    fact = next(iter(facts))
    scalar = _scalar(expr, {}, context, model)
    mentioned: set[str] = set()
    _filter_tables(expr, context, mentioned, model)
    _extra_tables(expr, mentioned)
    tables = tuple(table for table in mentioned if table != fact)
    return fact, scalar, tables, expr


def _aggregate(call: Call) -> tuple[str, exp.Expression]:
    name = call.name.casefold()
    if name == "countrows":
        arg = call.args[0]
        if not isinstance(arg, TableRef):
            raise DaxError("COUNTROWS expects a table", call.line, call.col)
        return arg.name, exp.Count(this=exp.Star())
    arg = call.args[0]
    if not isinstance(arg, ColumnRef):
        raise DaxError(f"{call.name} expects one column", call.line, call.col)
    column = exp.column(arg.column, table=arg.table, quoted=True)
    if name == "distinctcount":
        return arg.table, exp.Count(this=exp.Distinct(expressions=[column]))
    functions = {
        "sum": exp.Sum,
        "average": exp.Avg,
        "min": exp.Min,
        "max": exp.Max,
        "count": exp.Count,
        "counta": exp.Count,
    }
    return arg.table, cast(exp.Expression, functions[name](this=column))


def _facts(expr: Expr, found: set[str]) -> None:
    if isinstance(expr, Call) and expr.name.casefold() in AGGREGATES:
        found.add(_fact_of(expr))
        return
    if isinstance(expr, Call) and expr.name.casefold() in ITERATORS:
        found.add(_iterated(expr.args[0]))
        return
    if isinstance(expr, Call) and expr.name.casefold() in CONTEXT:
        return
    for child in _children(expr):
        _facts(child, found)


def _context_tables(expr: Expr, found: set[str]) -> None:
    if isinstance(expr, Call) and expr.name.casefold() in CONTEXT - {"isfiltered"}:
        arg = expr.args[0]
        if isinstance(arg, ColumnRef):
            found.add(arg.table)
        return
    for child in _children(expr):
        _context_tables(child, found)


def _extra_tables(expr: Expr, found: set[str]) -> None:
    """Tables a measure reads besides its filters: RELATED columns and context-function columns."""
    if isinstance(expr, Call) and expr.name.casefold() in {"related", "selectedvalue", "hasonevalue"}:
        arg = expr.args[0] if expr.args else None
        if isinstance(arg, ColumnRef):
            found.add(arg.table)
    for child in _children(expr):
        _extra_tables(child, found)


def _iterated(source: Expr) -> str:
    if isinstance(source, TableRef):
        return source.name
    if isinstance(source, Call) and source.name.casefold() == "filter" and source.args and isinstance(source.args[0], TableRef):
        return source.args[0].name
    raise DaxError("an iterator walks a table, or FILTER(<table>, <condition>)", source.line, source.col)


def _fact_of(call: Call) -> str:
    arg = call.args[0]
    if isinstance(arg, TableRef):
        return arg.name
    if isinstance(arg, ColumnRef):
        return arg.table
    raise DaxError(f"{call.name} expects a column or a table", call.line, call.col)


def _children(expr: Expr) -> tuple[Expr, ...]:
    if isinstance(expr, Call):
        return expr.args
    if isinstance(expr, Unary):
        return (expr.expr,)
    if isinstance(expr, Binary):
        return (expr.left, expr.right)
    if isinstance(expr, InExpr):
        return (expr.expr, *expr.values)
    if isinstance(expr, VarBlock):
        return tuple(value for _name, value in expr.bindings) + (expr.body,)
    return ()


def _scalar(
    expr: Expr,
    scope: dict[str, Expr],
    filters: tuple[Constraint, ...],
    model: DatasetDefinition,
) -> exp.Expression:
    if isinstance(expr, NumberLit):
        return exp.Literal.number(expr.value)
    if isinstance(expr, StringLit):
        return exp.Literal.string(expr.value)
    if isinstance(expr, BoolLit):
        return exp.Boolean(this=expr.value)
    if isinstance(expr, NameRef):
        if expr.name.casefold() not in scope:
            raise DaxError(f"name {expr.name!r} does not exist", expr.line, expr.col)
        return _scalar(scope[expr.name.casefold()], scope, filters, model)
    if isinstance(expr, Unary):
        operand = _scalar(expr.expr, scope, filters, model)
        if expr.op == "+":
            return operand
        if expr.op == "-":
            return exp.Neg(this=operand)
        return exp.Not(this=operand)
    if isinstance(expr, Binary):
        return _binary(expr, scope, filters, model)
    if isinstance(expr, InExpr):
        return exp.In(
            this=_scalar(expr.expr, scope, filters, model),
            expressions=[
                _scalar(value, scope, filters, model) for value in expr.values
            ],
        )
    if isinstance(expr, VarBlock):
        local = dict(scope)
        for name, value in expr.bindings:
            local[name.casefold()] = value
        return _scalar(expr.body, local, filters, model)
    if isinstance(expr, Call):
        return _call(expr, scope, filters, model)
    if isinstance(expr, ColumnRef):
        return exp.column(expr.column, table=expr.table, quoted=True)
    raise DaxError("this expression cannot be compiled", expr.line, expr.col)


def _call(
    expr: Call,
    scope: dict[str, Expr],
    filters: tuple[Constraint, ...],
    model: DatasetDefinition,
) -> exp.Expression:
    name = expr.name.casefold()
    if name == "totalytd":
        if len(expr.args) != 2:
            raise DaxError(
                "TOTALYTD expects an expression and the date column",
                expr.line,
                expr.col,
            )
        return _scalar(
            expr.args[0], scope, _ytd(filters, expr.args[1], expr, model), model
        )
    if name == "calculate":
        if not expr.args:
            raise DaxError("CALCULATE expects an expression", expr.line, expr.col)
        updated = filters
        for modifier in expr.args[1:]:
            updated = _apply(updated, modifier, expr, model)
        return _scalar(expr.args[0], scope, updated, model)
    if name in AGGREGATES:
        return _where(_aggregate(expr)[1], filters)
    special = _special(expr, scope, filters, model)
    if special is not None:
        return special
    args = [_scalar(arg, scope, filters, model) for arg in expr.args]
    plain = _plain(name, args, expr)
    if plain is not None:
        return plain
    if name == "blank":
        return exp.Null()
    if name == "isblank":
        return exp.Is(this=args[0], expression=exp.Null())
    if name in {"true", "false"}:
        return exp.Boolean(this=name == "true")
    if name == "not":
        return exp.Not(this=args[0])
    if name == "and":
        return exp.And(this=args[0], expression=args[1])
    if name == "or":
        return exp.Or(this=args[0], expression=args[1])
    if name == "if":
        if len(args) not in {2, 3}:
            raise DaxError("IF expects two or three arguments", expr.line, expr.col)
        otherwise = args[2] if len(args) == 3 else exp.Null()
        return exp.If(this=args[0], true=args[1], false=otherwise)
    if name == "divide":
        return _divide(expr, scope, filters, model)
    if name in IDENTITY:
        raise DaxError(f"{expr.name.upper()}() works only in row-level security rules", expr.line, expr.col)
    raise DaxError(f"{expr.name} cannot be compiled yet", expr.line, expr.col)


# ---------------------------------------------------------------- functions added for Power BI parity


_ITERATED = {"sumx": exp.Sum, "averagex": exp.Avg, "minx": exp.Min, "maxx": exp.Max, "countx": exp.Count}
_INTERVALS = {"DAY": "day", "WEEK": "week", "MONTH": "month", "QUARTER": "quarter", "YEAR": "year"}


def _arity(expr: Call, low: int, high: int | None = None) -> None:
    high = low if high is None else high
    if not low <= len(expr.args) <= high:
        count = str(low) if low == high else f"{low} to {high}"
        raise DaxError(f"{expr.name.upper()} expects {count} arguments", expr.line, expr.col)


def _special(
    expr: Call,
    scope: dict[str, Expr],
    filters: tuple[Constraint, ...],
    model: DatasetDefinition,
) -> exp.Expression | None:
    """Functions that read the filter context, a table, or a keyword argument."""
    name = expr.name.casefold()
    if name in _ITERATED:
        source = expr.args[0]
        rows = filters
        if isinstance(source, Call):
            _arity(source, 2)
            rows = filters + _constraints(source.args[1], source)
        row = _scalar(expr.args[1], scope, (), model)
        return _where(cast(exp.Expression, _ITERATED[name](this=row)), rows)
    if name == "related":
        arg = expr.args[0]
        if not isinstance(arg, ColumnRef):
            raise DaxError("RELATED expects one column", expr.line, expr.col)
        return exp.column(arg.column, table=arg.table, quoted=True)
    if name in {"selectedvalue", "hasonevalue"}:
        column = expr.args[0]
        if not isinstance(column, ColumnRef):
            raise DaxError(f"{expr.name.upper()} expects a column", expr.line, expr.col)
        ref = exp.column(column.column, table=column.table, quoted=True)
        one = exp.EQ(this=_where(exp.Count(this=exp.Distinct(expressions=[ref])), filters), expression=exp.Literal.number(1))
        if name == "hasonevalue":
            return one
        alternate = _scalar(expr.args[1], scope, filters, model) if len(expr.args) == 2 else exp.Null()
        return exp.If(this=one, true=_where(exp.Min(this=ref.copy()), filters), false=alternate)
    if name == "isfiltered":
        column = expr.args[0]
        if not isinstance(column, ColumnRef):
            raise DaxError("ISFILTERED expects a column", expr.line, expr.col)
        return exp.Boolean(this=any((column.table, column.column) in item.columns for item in filters))
    if name in {"totalqtd", "totalmtd"}:
        _arity(expr, 2)
        period = "quarter" if name == "totalqtd" else "month"
        return _scalar(expr.args[0], scope, _to_date(filters, expr.args[1], expr, model, period), model)
    if name == "datediff":
        _arity(expr, 3)
        interval = expr.args[2]
        if not isinstance(interval, NameRef) or interval.name.upper() not in _INTERVALS:
            raise DaxError("DATEDIFF interval must be DAY, WEEK, MONTH, QUARTER or YEAR", expr.line, expr.col)
        start, end = (_date(_scalar(arg, scope, filters, model)) for arg in expr.args[:2])
        return exp.Anonymous(this="DATE_DIFF", expressions=[exp.Literal.string(_INTERVALS[interval.name.upper()]), start, end])
    if name == "weekday":
        _arity(expr, 1, 2)
        kind = expr.args[1] if len(expr.args) == 2 else NumberLit(1, expr.line, expr.col)
        if not isinstance(kind, NumberLit) or kind.value not in {1, 2, 3}:
            raise DaxError("WEEKDAY type must be 1, 2 or 3", expr.line, expr.col)
        day = _date(_scalar(expr.args[0], scope, filters, model))
        if kind.value == 1:  # Sunday 1 … Saturday 7
            return exp.Add(this=exp.Anonymous(this="DAYOFWEEK", expressions=[day]), expression=exp.Literal.number(1))
        iso = exp.Anonymous(this="ISODOW", expressions=[day])  # Monday 1 … Sunday 7
        return iso if kind.value == 2 else exp.Sub(this=iso, expression=exp.Literal.number(1))
    if name == "format":
        _arity(expr, 2)
        pattern = expr.args[1]
        if not isinstance(pattern, StringLit):
            raise DaxError("FORMAT expects a format in quotes, such as \"#,0\" or \"dd mmm yyyy\"", expr.line, expr.col)
        return _format(_scalar(expr.args[0], scope, filters, model), pattern.value, expr)
    if name == "switch":
        return _switch(expr, scope, filters, model)
    if name == "rankx":
        return _rankx(expr, scope, filters, model)
    return None


def _plain(name: str, args: list[exp.Expression], expr: Call) -> exp.Expression | None:
    """Scalar functions that map straight onto SQL."""
    one = {"upper": exp.Upper, "lower": exp.Lower, "abs": exp.Abs, "int": exp.Floor}
    if name in one:
        _arity(expr, 1)
        return cast(exp.Expression, one[name](this=args[0]))
    if name == "len":
        _arity(expr, 1)
        return exp.Length(this=_blank_text(args[0]))
    if name in {"left", "right"}:
        _arity(expr, 2)
        return exp.Anonymous(this=name.upper(), expressions=[args[0], args[1]])
    if name == "mid":
        _arity(expr, 3)
        return exp.Substring(this=args[0], start=args[1], length=args[2])
    if name == "concatenate":
        _arity(expr, 2)
        return exp.DPipe(this=_blank_text(args[0]), expression=_blank_text(args[1]))
    if name == "coalesce":
        if len(args) < 2:
            raise DaxError("COALESCE expects two or more arguments", expr.line, expr.col)
        return exp.Coalesce(this=args[0], expressions=args[1:])
    if name == "iferror":
        _arity(expr, 2)
        # Division by zero is already blank here, and DuckDB's TRY cannot wrap an
        # aggregate, so over an aggregate a blank result takes the alternate too.
        inner = args[0] if args[0].find(exp.AggFunc) else exp.Anonymous(this="TRY", expressions=[args[0]])
        return exp.Coalesce(this=inner, expressions=[args[1]])
    if name == "round":
        _arity(expr, 1, 2)
        digits = args[1] if len(args) == 2 else exp.Literal.number(0)
        return exp.Round(this=args[0], decimals=digits)
    if name == "mod":
        _arity(expr, 2)
        # The remainder takes the divisor's sign, as in DAX.
        quotient = exp.Floor(this=exp.Div(this=args[0].copy(), expression=exp.Nullif(this=args[1].copy(), expression=exp.Literal.number(0))))
        return exp.Sub(this=args[0], expression=exp.Mul(this=args[1], expression=quotient))
    if name == "power":
        _arity(expr, 2)
        return exp.Pow(this=args[0], expression=args[1])
    if name in {"year", "month", "day"}:
        _arity(expr, 1)
        return exp.Anonymous(this=name.upper(), expressions=[_date(args[0])])
    if name == "today":
        _arity(expr, 0)
        return exp.CurrentDate()
    if name == "date":
        _arity(expr, 3)
        return exp.Anonymous(this="MAKE_DATE", expressions=args)
    if name == "eomonth":
        _arity(expr, 2)
        moved = exp.Add(this=_date(args[0]), expression=exp.Anonymous(this="TO_MONTHS", expressions=[exp.Cast(this=args[1], to=exp.DataType.build("INTEGER"))]))
        return exp.Anonymous(this="LAST_DAY", expressions=[moved])
    return None


def _date(value: exp.Expression) -> exp.Expression:
    return exp.Cast(this=value, to=exp.DataType.build("DATE"))


def _switch(
    expr: Call,
    scope: dict[str, Expr],
    filters: tuple[Constraint, ...],
    model: DatasetDefinition,
) -> exp.Expression:
    """SWITCH(value, match, result, …, [else]); SWITCH(TRUE(), condition, result, …) tests conditions."""
    if len(expr.args) < 3:
        raise DaxError("SWITCH expects a value, then pairs of match and result", expr.line, expr.col)
    first = expr.args[0]
    tests_conditions = isinstance(first, BoolLit) and first.value or (
        isinstance(first, Call) and first.name.casefold() == "true"
    )
    pairs = expr.args[1:]
    otherwise = _scalar(pairs[-1], scope, filters, model) if len(pairs) % 2 else exp.Null()
    ifs: list[exp.Expression] = []
    for match, result in zip(pairs[0::2], pairs[1::2], strict=False):
        condition = (
            _scalar(match, scope, filters, model)
            if tests_conditions
            else _eq(_scalar(first, scope, filters, model), _scalar(match, scope, filters, model))
        )
        ifs.append(exp.If(this=condition, true=_scalar(result, scope, filters, model)))
    return exp.Case(ifs=ifs, default=otherwise)


def _rankx(
    expr: Call,
    scope: dict[str, Expr],
    filters: tuple[Constraint, ...],
    model: DatasetDefinition,
) -> exp.Expression:
    """RANKX(ALL(...), <expression>, , [ASC|DESC], [SKIP|DENSE]) as a rank over the visual's rows."""
    _arity(expr, 2, 5)
    table = expr.args[0]
    if not (isinstance(table, TableRef) or (isinstance(table, Call) and table.name.casefold() in {"all", "removefilters"})):
        raise DaxError("RANKX ranks over ALL(<table or column>)", expr.line, expr.col)
    if len(expr.args) >= 3 and not (isinstance(expr.args[2], Call) and expr.args[2].name.casefold() == "blank"):
        raise DaxError("RANKX's third argument (a value to rank) isn't supported yet; leave it empty or BLANK()", expr.line, expr.col)
    words = [arg.name.upper() for arg in expr.args[3:] if isinstance(arg, NameRef)]
    if len(words) != len(expr.args[3:]) or any(word not in {"ASC", "DESC", "SKIP", "DENSE"} for word in words):
        raise DaxError("RANKX order is ASC or DESC, and ties are SKIP or DENSE", expr.line, expr.col)
    value = _scalar(expr.args[1], scope, filters, model)
    kind = "DENSE_RANK" if "DENSE" in words else "RANK"
    ordered = exp.Ordered(this=value, desc="ASC" not in words, nulls_first=False)
    return exp.Window(this=exp.Anonymous(this=kind, expressions=[]), order=exp.Order(expressions=[ordered]))


_DATE_TOKENS = (("yyyy", "%Y"), ("yy", "%y"), ("mmmm", "%B"), ("mmm", "%b"), ("mm", "%m"), ("dddd", "%A"), ("ddd", "%a"), ("dd", "%d"))
_NUMBER_FORMAT = re.compile(r"^(#,)?0(?:\.(0+))?(%?)$")


def _format(value: exp.Expression, pattern: str, at: Call) -> exp.Expression:
    """FORMAT for the common Power BI patterns: numbers (#,0 / 0.0 / 0%) and dates (dd mmm yyyy…)."""
    number = _NUMBER_FORMAT.match(pattern.strip())
    if number:
        digits = len(number.group(2) or "")
        grouping = "," if number.group(1) else ""
        if number.group(3):
            value = exp.Mul(this=value, expression=exp.Literal.number(100))
        decimal = exp.Cast(this=value, to=exp.DataType.build("DOUBLE"))
        suffix = "%" if number.group(3) else ""
        return exp.Anonymous(this="FORMAT", expressions=[exp.Literal.string(f"{{:{grouping}.{digits}f}}{suffix}"), decimal])
    if any(token in pattern.lower() for token, _ in _DATE_TOKENS):
        out, rest = "", pattern
        while rest:
            for token, code in _DATE_TOKENS:
                if rest.lower().startswith(token):
                    out += code
                    rest = rest[len(token):]
                    break
            else:
                out += rest[0].replace("%", "%%")
                rest = rest[1:]
        return exp.Anonymous(this="STRFTIME", expressions=[exp.Cast(this=value, to=exp.DataType.build("DATE")), exp.Literal.string(out)])
    raise DaxError('FORMAT supports "0", "0.0", "#,0", "#,0.00", "0%", "0.0%" and dates such as "dd mmm yyyy" or "mmm yy"', at.line, at.col)


def _divide(
    expr: Call,
    scope: dict[str, Expr],
    filters: tuple[Constraint, ...],
    model: DatasetDefinition,
) -> exp.Expression:
    if len(expr.args) not in {2, 3}:
        raise DaxError("DIVIDE expects two or three arguments", expr.line, expr.col)
    num = _scalar(expr.args[0], scope, filters, model)
    den = _scalar(expr.args[1], scope, filters, model)
    zero = exp.Literal.number(0)
    if len(expr.args) == 2:
        return exp.Div(this=num, expression=exp.Nullif(this=den, expression=zero))
    alt = _scalar(expr.args[2], scope, filters, model)
    den_again = _scalar(expr.args[1], scope, filters, model)
    blank = exp.or_(
        exp.EQ(this=den, expression=zero),
        exp.Is(this=den_again, expression=exp.Null()),
    )
    return exp.If(this=blank, true=alt, false=exp.Div(this=num, expression=den.copy()))


def _binary(
    expr: Binary,
    scope: dict[str, Expr],
    filters: tuple[Constraint, ...],
    model: DatasetDefinition,
) -> exp.Expression:
    left = _scalar(expr.left, scope, filters, model)
    right = _scalar(expr.right, scope, filters, model)
    if expr.op in {"+", "-"}:
        left = _zero(left)
        right = _zero(right)
    if expr.op == "+":
        return exp.Add(this=left, expression=right)
    if expr.op == "-":
        return exp.Sub(this=left, expression=right)
    if expr.op == "*":
        return exp.Mul(this=left, expression=right)
    if expr.op == "/":
        return exp.Div(
            this=left,
            expression=exp.Nullif(this=right, expression=exp.Literal.number(0)),
        )
    if expr.op == "&":
        return exp.DPipe(this=_blank_text(left), expression=_blank_text(right))
    if expr.op == "=":
        return _eq(left, right)
    if expr.op == "<>":
        return exp.Not(this=_eq(left.copy(), right.copy()))
    compared = {">": exp.GT, "<": exp.LT, ">=": exp.GTE, "<=": exp.LTE}
    if expr.op in compared:
        return cast(exp.Expression, compared[expr.op](this=left, expression=right))
    if expr.op == "and":
        return exp.And(this=left, expression=right)
    return exp.Or(this=left, expression=right)


def _zero(expr: exp.Expression) -> exp.Expression:
    return exp.Coalesce(this=expr, expressions=[exp.Literal.number(0)])


def _blank_text(expr: exp.Expression) -> exp.Expression:
    return exp.Coalesce(this=expr, expressions=[exp.Literal.string("")])


def _eq(left: exp.Expression, right: exp.Expression) -> exp.Expression:
    return cast(
        exp.Expression,
        exp.or_(
            exp.EQ(this=left, expression=right),
            exp.and_(
                exp.Is(this=left.copy(), expression=exp.Null()),
                exp.Is(this=right.copy(), expression=exp.Null()),
            ),
        ),
    )


def _filter_tables(
    expr: Expr,
    filters: tuple[Constraint, ...],
    found: set[str],
    model: DatasetDefinition,
) -> None:
    if isinstance(expr, Call) and expr.name.casefold() == "calculate":
        updated = filters
        for modifier in expr.args[1:]:
            updated = _apply(updated, modifier, expr, model)
        if expr.args:
            _filter_tables(expr.args[0], updated, found, model)
        return
    for item in filters:
        for table, _column in item.columns:
            found.add(table)
    for child in _children(expr):
        _filter_tables(child, filters, found, model)


def _apply(
    filters: tuple[Constraint, ...],
    modifier: Expr,
    at: Call,
    model: DatasetDefinition,
) -> tuple[Constraint, ...]:
    if isinstance(modifier, Call) and modifier.name.casefold() == "sameperiodlastyear":
        return _shift_dates(filters, modifier, model, years=-1)
    if isinstance(modifier, Call) and modifier.name.casefold() == "dateadd":
        return _dateadd(filters, modifier, model)
    if isinstance(modifier, Call) and modifier.name.casefold() == "datesytd":
        _arity(modifier, 1)
        return _ytd(filters, modifier.args[0], modifier, model)
    if isinstance(modifier, Call) and modifier.name.casefold() in {"previousmonth", "previousyear", "parallelperiod"}:
        return _whole_periods(filters, modifier, model)
    if isinstance(modifier, Call) and modifier.name.casefold() in {
        "all",
        "removefilters",
    }:
        return _remove(filters, modifier)
    if isinstance(modifier, Call) and modifier.name.casefold() == "filter":
        if len(modifier.args) != 2:
            raise DaxError("FILTER expects a table and a predicate", at.line, at.col)
        return filters + _constraints(modifier.args[1], at)
    added = _constraints(modifier, at)
    covered = {column for item in added for column in item.columns}
    kept = tuple(item for item in filters if not covered.intersection(item.columns))
    return kept + added


def _remove(filters: tuple[Constraint, ...], call: Call) -> tuple[Constraint, ...]:
    if len(call.args) == 1 and isinstance(call.args[0], TableRef):
        table = call.args[0].name
        return tuple(
            item
            for item in filters
            if any(name != table for name, _column in item.columns)
        )
    columns: list[tuple[str, str]] = []
    for arg in call.args:
        if not isinstance(arg, ColumnRef):
            raise DaxError("ALL expects a table or columns", call.line, call.col)
        columns.append((arg.table, arg.column))
    blocked = set(columns)
    return tuple(item for item in filters if not blocked.intersection(item.columns))


def _constraints(expr: Expr, at: Call) -> tuple[Constraint, ...]:
    if isinstance(expr, Binary) and expr.op == "and":
        return _constraints(expr.left, at) + _constraints(expr.right, at)
    if isinstance(expr, Unary) and expr.op == "not":
        inner = _constraints(expr.expr, at)
        flipped: list[Constraint] = []
        for item in inner:
            if item.op not in _FLIP or len(item.columns) != 1:
                raise DaxError("NOT can only invert a comparison", at.line, at.col)
            flipped.append(Constraint(item.columns, _FLIP[item.op], item.value))
        return tuple(flipped)
    if (
        isinstance(expr, Binary)
        and expr.op in _OPS
        and isinstance(expr.left, ColumnRef)
    ):
        return (
            Constraint(
                ((expr.left.table, expr.left.column),),
                expr.op,
                _literal(expr.right, at),
            ),
        )
    if isinstance(expr, InExpr) and isinstance(expr.expr, ColumnRef):
        return (
            Constraint(
                ((expr.expr.table, expr.expr.column),),
                "in",
                tuple(_literal(value, at) for value in expr.values),
            ),
        )
    raise DaxError("CALCULATE filter is not a comparison", at.line, at.col)


def _literal(expr: Expr, at: Call) -> object:
    if isinstance(expr, NumberLit | StringLit | BoolLit):
        return expr.value
    raise DaxError("filter value must be a literal", at.line, at.col)


def filter_expression(filters: tuple[Constraint, ...]) -> exp.Expression | None:
    """AND of predicates. Used for a WHERE that CALCULATE must not replace."""
    condition: exp.Expression | None = None
    for item in filters:
        piece = _render(item)
        condition = (
            piece if condition is None else exp.And(this=condition, expression=piece)
        )
    return condition


def _where(
    aggregate: exp.Expression, filters: tuple[Constraint, ...]
) -> exp.Expression:
    if not filters:
        return aggregate
    condition: exp.Expression | None = None
    for item in filters:
        piece = _render(item)
        condition = (
            piece if condition is None else exp.And(this=condition, expression=piece)
        )
    return cast(exp.Expression, exp.Filter(this=aggregate, expression=condition))


def _render(item: Constraint) -> exp.Expression:
    table, column = item.columns[0]
    ref = exp.column(column, table=table, quoted=True)
    if item.op in {"in", "notIn"}:
        values = item.value if isinstance(item.value, tuple) else (item.value,)
        inside = cast(
            exp.Expression,
            exp.In(this=ref, expressions=[_sql_literal(value) for value in values]),
        )
        if item.op == "notIn":
            return exp.Not(this=inside)
        return inside
    if item.op == "isBlank":
        return exp.Is(this=ref, expression=exp.Null())
    if item.op == "isNotBlank":
        return exp.Not(this=exp.Is(this=ref, expression=exp.Null()))
    if item.op in {"contains", "startsWith"}:
        text = item.value if isinstance(item.value, str) else str(item.value)
        function = "contains" if item.op == "contains" else "starts_with"
        return exp.Anonymous(this=function, expressions=[ref, exp.Literal.string(text)])
    compared = {
        "=": exp.EQ,
        "<>": exp.NEQ,
        "<": exp.LT,
        ">": exp.GT,
        "<=": exp.LTE,
        ">=": exp.GTE,
    }
    return cast(
        exp.Expression,
        compared[item.op](this=ref, expression=_sql_literal(item.value)),
    )


def _sql_literal(value: object) -> exp.Expression:
    if isinstance(value, bool):
        return exp.Boolean(this=value)
    if isinstance(value, dt.datetime):
        value = value.date()
    if isinstance(value, dt.date):
        return cast(
            exp.Expression,
            exp.Cast(
                this=exp.Literal.string(value.isoformat()),
                to=exp.DataType.build("DATE"),
            ),
        )
    if isinstance(value, int | float):
        return exp.Literal.number(value)
    return exp.Literal.string(str(value))


def _shift_dates(
    filters: tuple[Constraint, ...],
    call: Call,
    model: DatasetDefinition,
    *,
    years: int = 0,
    months: int = 0,
    days: int = 0,
) -> tuple[Constraint, ...]:
    if len(call.args) != 1:
        raise DaxError(
            f"{call.name} expects the date table column", call.line, call.col
        )
    table, column = _date_key(call.args[0], call, model)
    hit = False
    shifted: list[Constraint] = []
    for item in filters:
        if (table, column) not in item.columns or item.op == "in":
            shifted.append(item)
            continue
        hit = True
        shifted.append(
            Constraint(
                item.columns,
                item.op,
                _move(item.value, years, months, days, call),
            )
        )
    if not hit:
        raise DaxError(f"{call.name} needs a date filter", call.line, call.col)
    return tuple(shifted)


def _dateadd(
    filters: tuple[Constraint, ...], call: Call, model: DatasetDefinition
) -> tuple[Constraint, ...]:
    count_arg = call.args[1] if len(call.args) == 3 else None
    if (
        isinstance(count_arg, Unary)
        and count_arg.op == "-"
        and isinstance(count_arg.expr, NumberLit)
    ):
        count_arg = NumberLit(-count_arg.expr.value, count_arg.line, count_arg.col)
    if (
        len(call.args) != 3
        or not isinstance(count_arg, NumberLit)
        or not isinstance(call.args[2], NameRef)
    ):
        raise DaxError(
            "DATEADD expects a date column, a number, and an interval",
            call.line,
            call.col,
        )
    count = count_arg.value
    if isinstance(count, float) and not count.is_integer():
        raise DaxError("DATEADD count must be a whole number", call.line, call.col)
    step = int(count)
    interval = call.args[2].name.casefold()
    years = months = days = 0
    if interval == "year":
        years = step
    elif interval == "quarter":
        months = 3 * step
    elif interval == "month":
        months = step
    elif interval == "day":
        days = step
    else:
        raise DaxError(
            "DATEADD interval must be DAY, MONTH, QUARTER, or YEAR",
            call.line,
            call.col,
        )
    column = call.args[0]
    if not isinstance(column, ColumnRef):
        raise DaxError("DATEADD expects the date table column", call.line, call.col)
    rewritten = Call(call.name, (column,), call.line, call.col)
    return _shift_dates(
        filters, rewritten, model, years=years, months=months, days=days
    )


def _ytd(
    filters: tuple[Constraint, ...],
    column: Expr,
    at: Call,
    model: DatasetDefinition,
) -> tuple[Constraint, ...]:
    table, name = _date_key(column, at, model)
    dates = [
        item.value
        for item in filters
        if (table, name) in item.columns and isinstance(item.value, dt.date)
    ]
    if not dates:
        raise DaxError("TOTALYTD needs a date filter", at.line, at.col)
    latest = max(dates)
    start_month = model.date_table.fiscal_year_start_month
    year = latest.year if latest.month >= start_month else latest.year - 1
    start = dt.date(year, start_month, 1)
    kept = tuple(item for item in filters if (table, name) not in item.columns)
    return kept + (
        Constraint(((table, name),), ">=", start),
        Constraint(((table, name),), "<=", latest),
    )


def _context_dates(filters: tuple[Constraint, ...], table: str, name: str, at: Call) -> list[dt.date]:
    dates: list[dt.date] = []
    for item in filters:
        if (table, name) not in item.columns:
            continue
        values = item.value if isinstance(item.value, tuple) else (item.value,)
        dates.extend(value.date() if isinstance(value, dt.datetime) else value for value in values if isinstance(value, dt.date))
    if not dates:
        raise DaxError(f"{at.name.upper()} needs a date filter", at.line, at.col)
    return dates


def _period_start(day: dt.date, period: str, fiscal_start: int = 1) -> dt.date:
    if period == "month":
        return day.replace(day=1)
    step = 3 if period == "quarter" else 12
    offset = (day.month - fiscal_start) % step
    month_index = day.month - 1 - offset
    return dt.date(day.year + month_index // 12, month_index % 12 + 1, 1)


def _to_date(
    filters: tuple[Constraint, ...], column: Expr, at: Call, model: DatasetDefinition, period: str
) -> tuple[Constraint, ...]:
    """Quarter or month to date: from the period's first day to the latest date in context."""
    table, name = _date_key(column, at, model)
    latest = max(_context_dates(filters, table, name, at))
    start = _period_start(latest, period, model.date_table.fiscal_year_start_month)
    kept = tuple(item for item in filters if (table, name) not in item.columns)
    return kept + (Constraint(((table, name),), ">=", start), Constraint(((table, name),), "<=", latest))


def _whole_periods(filters: tuple[Constraint, ...], call: Call, model: DatasetDefinition) -> tuple[Constraint, ...]:
    """PREVIOUSMONTH, PREVIOUSYEAR and PARALLELPERIOD: whole periods moved from the dates in context."""
    name = call.name.casefold()
    if name == "parallelperiod":
        _arity(call, 3)
        count, interval = call.args[1], call.args[2]
        if isinstance(count, Unary) and count.op == "-" and isinstance(count.expr, NumberLit):
            count = NumberLit(-count.expr.value, count.line, count.col)
        if not isinstance(count, NumberLit) or not isinstance(interval, NameRef) or interval.name.upper() not in {"MONTH", "QUARTER", "YEAR"}:
            raise DaxError("PARALLELPERIOD expects the date column, a whole number, and MONTH, QUARTER or YEAR", call.line, call.col)
        period, step = interval.name.lower(), int(count.value)
    else:
        _arity(call, 1)
        period, step = ("month", -1) if name == "previousmonth" else ("year", -1)
    table, key = _date_key(call.args[0], call, model)
    dates = _context_dates(filters, table, key, call)
    months = {"month": 1, "quarter": 3, "year": 12}[period] * step
    first = _move(_period_start(min(dates), period), 0, months, 0, call)
    last_start = _move(_period_start(max(dates), period), 0, months, 0, call)
    span = {"month": 1, "quarter": 3, "year": 12}[period]
    last = _move(last_start, 0, span, 0, call) - dt.timedelta(days=1)
    kept = tuple(item for item in filters if (table, key) not in item.columns)
    return kept + (Constraint(((table, key),), ">=", first), Constraint(((table, key),), "<=", last))


def _date_key(column: Expr, at: Call, model: DatasetDefinition) -> tuple[str, str]:
    marked = [table for table in model.tables if table.is_date_table]
    if len(marked) != 1 or marked[0].date_column is None:
        raise DaxError("a marked date table is required", at.line, at.col)
    if not isinstance(column, ColumnRef):
        raise DaxError(
            "time intelligence expects the date table column", at.line, at.col
        )
    table = marked[0]
    if column.table != table.name or column.column != table.date_column:
        raise DaxError(
            f"{column.table}[{column.column}] is not the date table key",
            at.line,
            at.col,
        )
    return table.name, table.date_column


def _move(value: object, years: int, months: int, days: int, at: Call) -> dt.date:
    if isinstance(value, dt.datetime):
        value = value.date()
    if not isinstance(value, dt.date):
        raise DaxError("the date filter must be a date", at.line, at.col)
    month_index = value.month - 1 + months
    year = value.year + years + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day) + dt.timedelta(days=days)


def _table(name: str) -> exp.Table:
    return exp.table_(name, quoted=True)


def _on(rel: RelationshipDef) -> exp.Expression:
    return exp.EQ(
        this=exp.column(rel.from_.column, table=rel.from_.table, quoted=True),
        expression=exp.column(rel.to.column, table=rel.to.table, quoted=True),
    )


def _join_kind(rel: RelationshipDef) -> str:
    return "left" if rel.join_type == "left" else "inner"
