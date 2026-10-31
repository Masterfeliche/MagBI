"""Resolve names in a formula against a dataset definition.

Table, column, and measure names match exactly, then case-insensitively when
one model name folds to the text. A measure reference is replaced by that
measure's formula. A cycle names every measure on the loop.
"""

from __future__ import annotations

from magbi.connectors.types import DataType
from magbi.dax.errors import DaxError
from magbi.dax.functions import AGGREGATES, CONTEXT, IDENTITY, ITERATORS, KEYWORDS
from magbi.dax.parser import (
    Binary,
    Call,
    ColumnRef,
    Expr,
    InExpr,
    MeasureRef,
    NameRef,
    TableRef,
    Unary,
    VarBlock,
    parse,
)
from magbi.model.schema import DatasetDefinition, MeasureDef, TableDef

MAX_DEPTH = 32

_NUMERIC = frozenset({DataType.INTEGER, DataType.DECIMAL})
_ORDERABLE = _NUMERIC | frozenset({DataType.STRING, DataType.DATE, DataType.DATETIME})


def bind(model: DatasetDefinition, source: str) -> Expr:
    """Parse ``source`` and resolve every name. The model is not modified."""
    return _Binder(model).expression(parse(source), (), {})


def bind_parsed(model: DatasetDefinition, expr: Expr) -> Expr:
    """Resolve every name in an already parsed (and possibly rewritten) expression."""
    return _Binder(model).expression(expr, (), {})


def bind_measure(model: DatasetDefinition, source: str) -> Expr:
    """Bind a measure and require an aggregation over columns of the right type."""
    expr = bind(model, source)
    _check_calls(model, expr)
    if not _aggregates(expr):
        raise DaxError("measures must aggregate", expr.line, expr.col)
    return expr


def bind_calculated_column(model: DatasetDefinition, source: str) -> Expr:
    """Bind a calculated column. Aggregations are rejected and nothing is executed."""
    expr = bind(model, source)
    if _aggregates(expr):
        raise DaxError(
            "calculated columns cannot contain aggregations", expr.line, expr.col
        )
    return expr


# Calls that read many rows and give one value: a measure must contain one.
_AGGREGATING = AGGREGATES | ITERATORS | (CONTEXT - {"isfiltered"})


def _aggregates(expr: Expr) -> bool:
    if isinstance(expr, Call) and expr.name.casefold() in _AGGREGATING:
        return True
    children: tuple[Expr, ...] = ()
    if isinstance(expr, Call):
        children = expr.args
    elif isinstance(expr, Unary):
        children = (expr.expr,)
    elif isinstance(expr, Binary):
        children = (expr.left, expr.right)
    elif isinstance(expr, InExpr):
        children = (expr.expr, *expr.values)
    elif isinstance(expr, VarBlock):
        children = tuple(value for _name, value in expr.bindings) + (expr.body,)
    return any(_aggregates(child) for child in children)


def _check_calls(model: DatasetDefinition, expr: Expr, row: str | None = None) -> None:
    """``row`` is the table an iterator walks, while checking its row expression."""
    if isinstance(expr, ColumnRef) and row is not None and expr.table != row:
        raise DaxError(
            f"{expr.table}[{expr.column}] is on another table: use RELATED({expr.table}[{expr.column}]) in a row expression",
            expr.line,
            expr.col,
        )
    if isinstance(expr, Call):
        name = expr.name.casefold()
        if name == "related":
            if row is None:
                raise DaxError("RELATED works only in the row expression of SUMX, AVERAGEX, MINX, MAXX or COUNTX", expr.line, expr.col)
            if len(expr.args) != 1 or not isinstance(expr.args[0], ColumnRef):
                raise DaxError("RELATED expects one column", expr.line, expr.col)
            return
        _check_call(model, expr)
        if name in ITERATORS:
            source = expr.args[0]
            table = source.name if isinstance(source, TableRef) else _iterated_table(source)
            _check_calls(model, source, None)
            if _aggregates(expr.args[1]):
                raise DaxError(
                    f"{expr.name.upper()} works row by row: its expression can use columns and RELATED, "
                    "not measures or aggregations, yet",
                    expr.line,
                    expr.col,
                )
            _check_calls(model, expr.args[1], table)
            return
        for arg in expr.args:
            _check_calls(model, arg, row)
        return
    if isinstance(expr, Unary):
        _check_calls(model, expr.expr, row)
    elif isinstance(expr, Binary):
        _check_calls(model, expr.left, row)
        _check_calls(model, expr.right, row)
    elif isinstance(expr, InExpr):
        _check_calls(model, expr.expr, row)
        for value in expr.values:
            _check_calls(model, value, row)
    elif isinstance(expr, VarBlock):
        for _name, value in expr.bindings:
            _check_calls(model, value, row)
        _check_calls(model, expr.body, row)


def _iterated_table(source: Expr) -> str:
    """The table an iterator walks: a table, or FILTER(table, condition)."""
    if isinstance(source, Call) and source.name.casefold() == "filter" and source.args and isinstance(source.args[0], TableRef):
        return source.args[0].name
    raise DaxError("an iterator walks a table, or FILTER(<table>, <condition>)", source.line, source.col)


def _check_call(model: DatasetDefinition, expr: Call) -> None:
    name = expr.name.casefold()
    if name in IDENTITY:
        raise DaxError(f"{expr.name.upper()}() works only in row-level security rules", expr.line, expr.col)
    if name == "countrows":
        if len(expr.args) != 1 or not isinstance(expr.args[0], TableRef):
            raise DaxError("COUNTROWS expects a table", expr.line, expr.col)
        return
    if name in ITERATORS:
        if len(expr.args) != 2:
            raise DaxError(f"{expr.name.upper()} expects a table and a row expression", expr.line, expr.col)
        if not isinstance(expr.args[0], TableRef):
            _iterated_table(expr.args[0])
        return
    if name in CONTEXT:
        limit = 2 if name == "selectedvalue" else 1
        if not 1 <= len(expr.args) <= limit or not isinstance(expr.args[0], ColumnRef):
            raise DaxError(f"{expr.name.upper()} expects a column", expr.line, expr.col)
        return
    if name == "rankx":
        if len(expr.args) < 2:
            raise DaxError("RANKX expects ALL(<table or column>) and an expression", expr.line, expr.col)
        if not _aggregates(expr.args[1]):
            raise DaxError("RANKX ranks by a measure or an aggregation", expr.line, expr.col)
        return
    if name not in AGGREGATES:
        return
    if len(expr.args) != 1 or not isinstance(expr.args[0], ColumnRef):
        raise DaxError(f"{expr.name} expects one column", expr.line, expr.col)
    column = expr.args[0]
    data_type = _column_type(model, column)
    if name in {"min", "max", "count", "counta", "distinctcount"}:
        allowed = _ORDERABLE
        kind = "a number, date, or string"
    else:
        allowed = _NUMERIC
        kind = "a numeric column"
    if data_type not in allowed:
        raise DaxError(
            f"{expr.name} requires {kind}. {column.table}[{column.column}] is {data_type.value}",
            expr.line,
            expr.col,
        )


def _column_type(model: DatasetDefinition, ref: ColumnRef) -> DataType:
    table = model.table(ref.table)
    if table is None:
        raise DaxError(f"table {ref.table!r} does not exist", ref.line, ref.col)
    for column in table.columns:
        if column.name == ref.column:
            return column.data_type
    for calculated in table.calculated_columns:
        if calculated.name == ref.column:
            return calculated.data_type
    raise DaxError(
        f"column {ref.table!r}.{ref.column!r} does not exist", ref.line, ref.col
    )


class _Binder:
    def __init__(self, model: DatasetDefinition) -> None:
        self._model = model

    def expression(
        self,
        expr: Expr,
        stack: tuple[str, ...],
        variables: dict[str, str],
    ) -> Expr:
        if isinstance(expr, ColumnRef):
            table, column = self._column(expr.table, expr.column, expr.line, expr.col)
            return ColumnRef(table, column, expr.line, expr.col)
        if isinstance(expr, MeasureRef):
            return self._measure(expr, stack)
        if isinstance(expr, NameRef):
            return self._name(expr, variables)
        if isinstance(expr, Call) and expr.name.casefold() == "dateadd":
            return self._dateadd(expr, stack, variables)
        if isinstance(expr, Call):
            args = tuple(self.expression(arg, stack, variables) for arg in expr.args)
            return Call(expr.name, args, expr.line, expr.col)
        if isinstance(expr, Unary):
            return Unary(
                expr.op,
                self.expression(expr.expr, stack, variables),
                expr.line,
                expr.col,
            )
        if isinstance(expr, Binary):
            return Binary(
                expr.op,
                self.expression(expr.left, stack, variables),
                self.expression(expr.right, stack, variables),
                expr.line,
                expr.col,
            )
        if isinstance(expr, InExpr):
            values = tuple(
                self.expression(value, stack, variables) for value in expr.values
            )
            return InExpr(
                self.expression(expr.expr, stack, variables),
                values,
                expr.line,
                expr.col,
            )
        if isinstance(expr, VarBlock):
            return self._var(expr, stack, variables)
        return expr

    def _var(
        self,
        expr: VarBlock,
        stack: tuple[str, ...],
        variables: dict[str, str],
    ) -> VarBlock:
        scope = dict(variables)
        bindings: list[tuple[str, Expr]] = []
        for name, value in expr.bindings:
            key = name.casefold()
            if key in scope:
                raise DaxError(
                    f"variable {name!r} is already defined", expr.line, expr.col
                )
            bound = self.expression(value, stack, scope)
            scope[key] = name
            bindings.append((name, bound))
        body = self.expression(expr.body, stack, scope)
        return VarBlock(tuple(bindings), body, expr.line, expr.col)

    def _dateadd(
        self,
        expr: Call,
        stack: tuple[str, ...],
        variables: dict[str, str],
    ) -> Call:
        if len(expr.args) != 3:
            raise DaxError(
                "DATEADD expects a date column, a number, and an interval",
                expr.line,
                expr.col,
            )
        column = self.expression(expr.args[0], stack, variables)
        count = self.expression(expr.args[1], stack, variables)
        interval = expr.args[2]
        if not isinstance(interval, NameRef) or interval.name.casefold() not in {
            "day",
            "month",
            "quarter",
            "year",
        }:
            raise DaxError(
                "DATEADD interval must be DAY, MONTH, QUARTER, or YEAR",
                expr.line,
                expr.col,
            )
        return Call(expr.name, (column, count, interval), expr.line, expr.col)

    def _name(self, expr: NameRef, variables: dict[str, str]) -> Expr:
        key = expr.name.casefold()
        if key in variables:
            return NameRef(variables[key], expr.line, expr.col)
        table = self._table_or_none(expr.name, expr.line, expr.col)
        if table is not None:
            return TableRef(table.name, expr.line, expr.col)
        if key in KEYWORDS:
            # An argument word such as MONTH in DATEDIFF or DESC in RANKX.
            return NameRef(expr.name.upper(), expr.line, expr.col)
        raise DaxError(f"name {expr.name!r} does not exist", expr.line, expr.col)

    def _measure(self, expr: MeasureRef, stack: tuple[str, ...]) -> Expr:
        found = self._measure_def(expr.name)
        if found is None:
            raise DaxError(f"measure {expr.name!r} does not exist", expr.line, expr.col)
        canonical = found.name
        if len(stack) >= MAX_DEPTH:
            raise DaxError(
                "measure expansion is nested too deeply", expr.line, expr.col
            )
        keys = [name.casefold() for name in stack]
        key = canonical.casefold()
        if key in keys:
            loop = list(stack[keys.index(key) :]) + [canonical]
            chain = " -> ".join(f"[{name}]" for name in loop)
            raise DaxError(f"circular reference: {chain}", expr.line, expr.col)
        body = parse(found.expression)
        return self.expression(body, stack + (canonical,), {})

    def _column(self, table: str, column: str, line: int, col: int) -> tuple[str, str]:
        owner = self._table(table, line, col)
        names = [column.name for column in owner.columns]
        names.extend(column.name for column in owner.calculated_columns)
        found = _pick(
            column,
            names,
            line,
            col,
            f"column {table!r}.{column!r} does not exist",
            f"column {column!r} is ambiguous on table {owner.name!r}",
        )
        return owner.name, found

    def _table(self, name: str, line: int, col: int) -> TableDef:
        found = self._table_or_none(name, line, col)
        if found is None:
            raise DaxError(f"table {name!r} does not exist", line, col)
        return found

    def _table_or_none(self, name: str, line: int, col: int) -> TableDef | None:
        exact = self._model.table(name)
        if exact is not None:
            return exact
        folded = [
            table
            for table in self._model.tables
            if table.name.casefold() == name.casefold()
        ]
        if len(folded) > 1:
            raise DaxError(f"table {name!r} is ambiguous", line, col)
        return folded[0] if folded else None

    def _measure_def(self, name: str) -> MeasureDef | None:
        found = self._model.measure(name)
        return None if found is None else found[1]


def _pick(
    wanted: str,
    options: list[str],
    line: int,
    col: int,
    missing: str,
    ambiguous: str,
) -> str:
    if wanted in options:
        return wanted
    folded = [name for name in options if name.casefold() == wanted.casefold()]
    if len(folded) == 1:
        return folded[0]
    if len(folded) > 1:
        raise DaxError(ambiguous, line, col)
    raise DaxError(missing, line, col)
