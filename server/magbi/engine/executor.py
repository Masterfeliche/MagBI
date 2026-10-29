"""Run generated SQL on a DuckDB connection and close nothing itself."""

from __future__ import annotations

from typing import Any

from magbi.engine.filter_context import BoundFilter, bind_filters
from magbi.engine.postprocess import shape
from magbi.engine.semantic import BoundQuery, SemanticQuery, bind_query
from magbi.engine.sql_gen import detail_sql, totals_sql
from magbi.model.schema import DatasetDefinition


def execute(con: Any, sql: str) -> list[tuple[object, ...]]:
    return [tuple(row) for row in con.execute(sql).fetchall()]


def run_query(
    model: DatasetDefinition, query: SemanticQuery, con: Any
) -> dict[str, object]:
    """Bind, generate, execute, and shape one query. ``con`` is DuckDB."""
    bound = bind_query(model, query)
    filters = bind_filters(model, query)
    rows = execute(con, detail_sql(model, bound, filters, probe=True))
    totals = _totals(model, bound, filters, con)
    return shape(bound, rows, totals)


def _totals(
    model: DatasetDefinition,
    bound: BoundQuery,
    filters: tuple[BoundFilter, ...],
    con: Any,
) -> tuple[object, ...] | None:
    if not bound.include_totals or not bound.measures:
        return None
    found = execute(con, totals_sql(model, bound, filters))
    if not found:
        return tuple(None for _measure in bound.measures)
    return found[0]
