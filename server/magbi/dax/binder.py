"""Resolve names in a formula against a dataset definition.

Table, column, and measure names match exactly, then case-insensitively when
one model name folds to the text. A measure reference is replaced by that
measure's formula. A cycle names every measure on the loop.
"""

from __future__ import annotations

from magbi.dax.errors import DaxError
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


def bind(model: DatasetDefinition, source: str) -> Expr:
    """Parse ``source`` and resolve every name. The model is not modified."""
    return _Binder(model).expression(parse(source), (), {})


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

    def _name(self, expr: NameRef, variables: dict[str, str]) -> Expr:
        key = expr.name.casefold()
        if key in variables:
            return NameRef(variables[key], expr.line, expr.col)
        table = self._table_or_none(expr.name, expr.line, expr.col)
        if table is not None:
            return TableRef(table.name, expr.line, expr.col)
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
