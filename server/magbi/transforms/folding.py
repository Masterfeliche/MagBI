"""Compile a leading run of transform steps into one DuckDB SELECT.

Folding stops at the first step that cannot be expressed in the dialect.
Later steps are returned unchanged for the Python executor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from sqlglot import exp

from magbi.transforms.errors import TransformError
from magbi.transforms.steps import (
    ChangeTypeStep,
    FilterRowsStep,
    RemoveColumnsStep,
    RemoveRowsStep,
    RenameColumnStep,
    SelectColumnsStep,
    TransformStep,
)

_COMPARISON = {
    "eq": exp.EQ,
    "neq": exp.NEQ,
    "gt": exp.GT,
    "gte": exp.GTE,
    "lt": exp.LT,
    "lte": exp.LTE,
}
_CASTS = {
    "string": "VARCHAR",
    "integer": "BIGINT",
    "decimal": "DOUBLE",
    "date": "DATE",
    "datetime": "TIMESTAMP",
    "boolean": "BOOLEAN",
}


@dataclass
class FoldResult:
    sql: str
    columns: tuple[str, ...]
    folded_count: int
    remaining: tuple[TransformStep, ...]


@dataclass
class _State:
    query: exp.Select
    columns: list[str]
    order: list[tuple[str, str]] = field(default_factory=list)
    limit: int | None = None
    distinct: bool = False


def fold(
    table: str,
    columns: tuple[str, ...],
    steps: tuple[TransformStep, ...],
    *,
    dialect: str = "duckdb",
) -> FoldResult:
    """Fold ``steps`` onto ``SELECT columns FROM table``."""
    selected = [_as(_col(name), name) for name in columns]
    state = _State(
        exp.select(*selected).from_(exp.table_(table, quoted=True)),
        list(columns),
    )
    folded = 0
    for index, step in enumerate(steps):
        nxt = _apply(state, step, dialect)
        if nxt is None:
            return FoldResult(
                _sql(state, dialect), tuple(state.columns), folded, steps[index:]
            )
        state = nxt
        folded += 1
    return FoldResult(_sql(state, dialect), tuple(state.columns), folded, ())


def _apply(_state: _State, step: TransformStep, dialect: str) -> _State | None:
    if isinstance(step, FilterRowsStep | RemoveRowsStep):
        _require(_state, step.column)
        predicate = _predicate(step.column, step.operator, step.value)
        if isinstance(step, RemoveRowsStep):
            predicate = exp.Not(this=predicate)
        return _wrap(_state, _keep(_state.columns), predicate)
    if isinstance(step, SelectColumnsStep):
        for name in step.columns:
            _require(_state, name)
        return _wrap(_state, _keep(list(step.columns)))
    if isinstance(step, RemoveColumnsStep):
        for name in step.columns:
            _require(_state, name)
        kept = [name for name in _state.columns if name not in step.columns]
        if not kept:
            raise TransformError("BAD_STEP", "removeColumns would leave no columns")
        return _wrap(_state, _keep(kept))
    if isinstance(step, RenameColumnStep):
        _require(_state, step.old_name)
        if step.new_name in _state.columns and step.new_name != step.old_name:
            raise TransformError(
                "DUPLICATE_COLUMN", f"column {step.new_name!r} already exists"
            )
        pairs: list[tuple[exp.Expression, str]] = [
            (cast(exp.Expression, _col(step.old_name)), step.new_name)
            if name == step.old_name
            else (cast(exp.Expression, _col(name)), name)
            for name in _state.columns
        ]
        return _wrap(_state, pairs)
    if isinstance(step, ChangeTypeStep):
        _require(_state, step.column)
        casted = exp.Cast(
            this=_col(step.column), to=exp.DataType.build(_CASTS[step.to_type])
        )
        cast_pairs: list[tuple[exp.Expression, str]] = [
            (cast(exp.Expression, casted), name)
            if name == step.column
            else (cast(exp.Expression, _col(name)), name)
            for name in _state.columns
        ]
        return _wrap(_state, cast_pairs)
    del dialect
    return None


def _keep(columns: list[str]) -> list[tuple[exp.Expression, str]]:
    return [(cast(exp.Expression, _col(name)), name) for name in columns]


def _wrap(
    state: _State,
    pairs: list[tuple[exp.Expression, str]],
    predicate: exp.Expression | None = None,
) -> _State:
    query = exp.select(*[_as(expr, name) for expr, name in pairs]).from_(
        _seal(state).subquery(alias="s")
    )
    if predicate is not None:
        query = query.where(predicate)
    return _State(query, [name for _expr, name in pairs])


def _seal(state: _State) -> exp.Select:
    query = state.query
    if state.distinct:
        query = query.distinct()
    for name, direction in state.order:
        query = query.order_by(exp.Ordered(this=_col(name), desc=direction == "desc"))
    if state.limit is not None:
        query = query.limit(state.limit)
    return query


def _sql(state: _State, dialect: str) -> str:
    return _seal(state).sql(dialect=dialect)


def _predicate(column: str, operator: str, value: object) -> exp.Expression:
    ref = _col(column)
    if operator == "isNull":
        return exp.Is(this=ref, expression=exp.Null())
    if operator == "isNotNull":
        return exp.Not(this=exp.Is(this=ref, expression=exp.Null()))
    if operator in {"contains", "startsWith", "endsWith"}:
        if not isinstance(value, str):
            raise TransformError("BAD_STEP", f"{operator} needs text")
        function = {
            "contains": "contains",
            "startsWith": "starts_with",
            "endsWith": "ends_with",
        }[operator]
        return exp.Anonymous(
            this=function, expressions=[ref, exp.Literal.string(value)]
        )
    if operator not in _COMPARISON:
        raise TransformError("BAD_STEP", f"operator {operator!r} is not supported")
    return cast(
        exp.Expression, _COMPARISON[operator](this=ref, expression=_literal(value))
    )


def _literal(value: object) -> exp.Expression:
    if value is None:
        return exp.Null()
    if isinstance(value, bool):
        return exp.Boolean(this=value)
    if isinstance(value, int | float):
        return exp.Literal.number(value)
    return exp.Literal.string(str(value))


def _require(state: _State, name: str) -> None:
    if name not in state.columns:
        raise TransformError("UNKNOWN_COLUMN", f"column {name!r} does not exist")


def _col(name: str) -> exp.Column:
    return exp.column(name, quoted=True)


def _as(expr: exp.Expression, name: str) -> exp.Expression:
    return cast(exp.Expression, expr.as_(name, quoted=True))
