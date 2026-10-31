"""Run generated SQL on a DuckDB connection and close nothing itself."""

from __future__ import annotations

from typing import Any

from magbi.dax.compiler import Constraint
from magbi.engine.filter_context import BoundFilter, bind_filters
from magbi.engine.grouping import fact_groups, ignored_filters
from magbi.engine.postprocess import shape
from magbi.engine.rls import role_filters
from magbi.engine.semantic import BoundQuery, SemanticQuery, bind_query
from magbi.engine.sql_gen import detail_sql, totals_sql
from magbi.model.schema import DatasetDefinition


def execute(con: Any, sql: str) -> list[tuple[object, ...]]:
    return [tuple(row) for row in con.execute(sql).fetchall()]


def run_query(
    model: DatasetDefinition,
    query: SemanticQuery,
    con: Any,
    *,
    roles: tuple[str, ...] = (),
    user: str | None = None,
) -> dict[str, object]:
    """Bind, generate, execute, and shape one query. ``con`` is DuckDB; ``user`` feeds USERPRINCIPALNAME()."""
    bound = bind_query(model, query)
    filters = bind_filters(model, query)
    secured = role_filters(model, roles, user)
    rows = execute(con, detail_sql(model, bound, filters, probe=True, rls=secured))
    totals = _totals(model, bound, filters, secured, con)
    result = shape(bound, rows, totals)
    skipped = ignored_filters(fact_groups(model, bound, filters))
    if skipped:
        result["ignoredFilters"] = skipped
    return result


def _totals(
    model: DatasetDefinition,
    bound: BoundQuery,
    filters: tuple[BoundFilter, ...],
    secured: tuple[Constraint, ...],
    con: Any,
) -> tuple[object, ...] | None:
    if not bound.include_totals or not bound.measures:
        return None
    found = execute(con, totals_sql(model, bound, filters, rls=secured))
    if not found:
        return tuple(None for _measure in bound.measures)
    return found[0]
