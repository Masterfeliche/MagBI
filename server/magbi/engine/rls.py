"""Role filters that stay outside the replaceable filter context.

The request names roles. There is no embed token until Sprint 7. A role filter
must be a comparison, IN, or AND of those.
"""

from __future__ import annotations

from magbi.dax.binder import bind
from magbi.dax.compiler import Constraint
from magbi.dax.errors import DaxError
from magbi.dax.parser import (
    Binary,
    BoolLit,
    ColumnRef,
    Expr,
    InExpr,
    NumberLit,
    StringLit,
)
from magbi.engine.errors import QueryError
from magbi.model.schema import DatasetDefinition, RlsRoleDef

_OPS = frozenset({"=", "<>", "<", ">", "<=", ">="})


def role_filters(
    model: DatasetDefinition, role_names: tuple[str, ...]
) -> tuple[Constraint, ...]:
    found: list[Constraint] = []
    for name in role_names:
        role = _role(model, name)
        for table_filter in role.table_filters:
            try:
                expr = bind(model, table_filter.expression)
            except DaxError as exc:
                raise QueryError("RLS_FILTER", str(exc)) from None
            found.extend(_constraints(expr))
    return tuple(found)


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
