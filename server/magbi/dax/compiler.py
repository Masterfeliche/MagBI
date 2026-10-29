"""Compile a measure to one DuckDB SELECT.

Aggregates on different tables are rejected. ``+`` and ``-`` treat NULL as 0.
``DIVIDE`` by zero is NULL. CALCULATE replaces filters on the columns it
mentions; ALL removes them. A table named by a filter or by ``also`` is joined
on the active relationship path.
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass
from typing import cast

from sqlglot import exp

from magbi.dax.binder import bind_measure
from magbi.dax.errors import DaxError
from magbi.dax.functions import AGGREGATES
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
from magbi.model.relationships import join_path
from magbi.model.schema import DatasetDefinition, ModelSchemaError, RelationshipDef

_OPS = {"=", "<>", "<", ">", "<=", ">="}
_FLIP = {"=": "<>", "<>": "=", "<": ">=", ">": "<=", "<=": ">", ">=": "<"}


@dataclass(frozen=True, slots=True)
class Constraint:
    """One filter. ``columns`` are the ones a later CALCULATE argument replaces."""

    columns: tuple[tuple[str, str], ...]
    op: str
    value: object


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
    expr = bind_measure(model, source)
    context = tuple(
        Constraint(((table, column),), op, value)
        for table, column, op, value in filters
    )
    facts: set[str] = set()
    _facts(expr, facts)
    if len(facts) != 1:
        raise DaxError(
            "measures that combine two fact tables are compiled by the query engine",
            expr.line,
            expr.col,
        )
    fact = next(iter(facts))
    query: exp.Select = exp.select(_scalar(expr, {}, context, model)).from_(
        _table(fact)
    )
    joined = {fact}
    mentioned: set[str] = set()
    _filter_tables(expr, context, mentioned, model)
    extras = list(also)
    for table in mentioned:
        if table != fact and table not in extras:
            extras.append(table)
    for extra in dict.fromkeys(extras):
        if extra in joined:
            continue
        try:
            path = join_path(model, fact, extra)
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
    for child in _children(expr):
        _facts(child, found)


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
    args = [_scalar(arg, scope, filters, model) for arg in expr.args]
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
    raise DaxError(f"{expr.name} cannot be compiled yet", expr.line, expr.col)


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
    if item.op == "in":
        values = item.value if isinstance(item.value, tuple) else (item.value,)
        return cast(
            exp.Expression,
            exp.In(this=ref, expressions=[_sql_literal(value) for value in values]),
        )
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
