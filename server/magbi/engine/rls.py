"""Role filters that stay outside the replaceable filter context.

The request, or the embed token, names roles. A role filter must be a
comparison, IN, or AND of those. Inside a rule on a table, ``[Column]`` means
that table's column.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from magbi.dax.binder import bind_parsed
from magbi.dax.compiler import Constraint
from magbi.dax.errors import DaxError
from magbi.dax.functions import IDENTITY
from magbi.dax.parser import (
    Binary,
    BoolLit,
    Call,
    ColumnRef,
    Expr,
    InExpr,
    MeasureRef,
    NumberLit,
    StringLit,
    parse,
)
from magbi.engine.errors import QueryError
from magbi.model.schema import DatasetDefinition, RlsRoleDef

_OPS = frozenset({"=", "<>", "<", ">", "<=", ">="})


def role_filters(
    model: DatasetDefinition, role_names: tuple[str, ...], user: str | None = None
) -> tuple[Constraint, ...]:
    """The filters of every named role. ``user`` is who is asking, for USERPRINCIPALNAME()."""
    found: list[Constraint] = []
    for name in role_names:
        role = _role(model, name)
        for table_filter in role.table_filters:
            try:
                expr = bind_rule(model, table_filter.table, table_filter.expression, user)
            except DaxError as exc:
                raise QueryError("RLS_FILTER", str(exc)) from None
            found.extend(_constraints(expr))
    return tuple(found)


def bind_rule(model: DatasetDefinition, table: str, source: str, user: str | None = None) -> Expr:
    """Bind a role's rule, as Power BI reads one.

    Inside a rule on a table, ``[Column]`` means that table's column, and
    USERPRINCIPALNAME() or USERNAME() is the signed-in user's email (or the
    embed token's user). With no user, such a rule matches nobody.
    """
    expr = _qualify(parse(source), model, table)
    return bind_parsed(model, _identity(expr, user))


def _identity(expr: Any, user: str | None) -> Any:
    if isinstance(expr, Call) and expr.name.casefold() in IDENTITY:
        if expr.args:
            raise QueryError("RLS_FILTER", f"{expr.name.upper()}() takes no arguments")
        # No user means no rows: an empty string never equals a real email.
        return StringLit(value=(user or "").strip().lower(), line=expr.line, col=expr.col)
    if not dataclasses.is_dataclass(expr) or isinstance(expr, type):
        return expr
    changes: dict[str, Any] = {}
    for field in dataclasses.fields(expr):
        value = getattr(expr, field.name)
        if dataclasses.is_dataclass(value):
            changes[field.name] = _identity(value, user)
        elif isinstance(value, tuple):
            changes[field.name] = tuple(_identity(item, user) for item in value)
    return dataclasses.replace(expr, **changes) if changes else expr


def _qualify(expr: Any, model: DatasetDefinition, table: str) -> Any:
    """Turn a bare ``[Name]`` that is a column of ``table``, and not a measure, into ``table[Name]``."""
    if isinstance(expr, MeasureRef):
        home = model.table(table)
        match = next((c.name for c in home.columns if c.name.casefold() == expr.name.casefold()), None) if home else None
        if match is not None and model.measure(expr.name) is None:
            return ColumnRef(table=table, column=match, line=expr.line, col=expr.col)
        return expr
    if not dataclasses.is_dataclass(expr) or isinstance(expr, type):
        return expr
    changes: dict[str, Any] = {}
    for field in dataclasses.fields(expr):
        value = getattr(expr, field.name)
        if dataclasses.is_dataclass(value):
            changes[field.name] = _qualify(value, model, table)
        elif isinstance(value, tuple):
            changes[field.name] = tuple(_qualify(item, model, table) for item in value)
    return dataclasses.replace(expr, **changes) if changes else expr


def _role(model: DatasetDefinition, name: str) -> RlsRoleDef:
    folded = [role for role in model.roles if role.name.casefold() == name.casefold()]
    if len(folded) == 1:
        return folded[0]
    raise QueryError("UNKNOWN_ROLE", f"role {name!r} does not exist")


def _constraints(expr: Expr) -> list[Constraint]:
    if isinstance(expr, Binary) and expr.op == "and":
        return _constraints(expr.left) + _constraints(expr.right)
    if (
        isinstance(expr, Binary)
        and expr.op in _OPS
        and isinstance(expr.left, ColumnRef)
    ):
        return [
            Constraint(
                ((expr.left.table, expr.left.column),),
                expr.op,
                _literal(expr.right),
            )
        ]
    if isinstance(expr, InExpr) and isinstance(expr.expr, ColumnRef):
        return [
            Constraint(
                ((expr.expr.table, expr.expr.column),),
                "in",
                tuple(_literal(value) for value in expr.values),
            )
        ]
    raise QueryError(
        "RLS_FILTER",
        "a role filter must be a comparison, IN, or AND of those",
    )


def _literal(expr: Expr) -> object:
    if isinstance(expr, NumberLit | StringLit | BoolLit):
        return expr.value
    raise QueryError("RLS_FILTER", "a role filter value must be a literal")
