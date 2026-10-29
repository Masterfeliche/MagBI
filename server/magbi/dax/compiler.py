"""Compile one aggregate measure to DuckDB SQL.

A column that is not on the aggregated table is reached by the active
relationship path. Scalar expressions and CALCULATE are later steps; this
function accepts a single aggregate, plus extra tables that must be joined.
"""

from __future__ import annotations

from typing import cast

from sqlglot import exp

from magbi.dax.binder import bind_measure
from magbi.dax.errors import DaxError
from magbi.dax.functions import AGGREGATES
from magbi.dax.parser import Call, ColumnRef, TableRef
from magbi.model.relationships import join_path
from magbi.model.schema import DatasetDefinition, ModelSchemaError, RelationshipDef


def compile_measure(
    model: DatasetDefinition, source: str, *, also: tuple[str, ...] = ()
) -> str:
    """Return DuckDB SQL for one aggregate. ``also`` tables are joined in."""
    expr = bind_measure(model, source)
    if not isinstance(expr, Call) or expr.name.casefold() not in AGGREGATES:
        raise DaxError(
            "only a single aggregate can be compiled here", expr.line, expr.col
        )
    return _select(model, expr, also).sql(dialect="duckdb")


def _select(model: DatasetDefinition, call: Call, also: tuple[str, ...]) -> exp.Select:
    fact, aggregate = _aggregate(call)
    query: exp.Select = exp.select(aggregate).from_(_table(fact))
    joined = {fact}
    for extra in dict.fromkeys(also):
        if extra in joined:
            continue
        try:
            path = join_path(model, fact, extra)
        except ModelSchemaError as exc:
            raise DaxError(str(exc), call.line, call.col) from None
        cursor = fact
        for rel in path:
            nxt = rel.to.table if rel.from_.table == cursor else rel.from_.table
            if nxt not in joined:
                query = query.join(_table(nxt), on=_on(rel), join_type=_join_kind(rel))
                joined.add(nxt)
            cursor = nxt
    return query


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


def _table(name: str) -> exp.Table:
    return exp.table_(name, quoted=True)


def _on(rel: RelationshipDef) -> exp.Expression:
    return exp.EQ(
        this=exp.column(rel.from_.column, table=rel.from_.table, quoted=True),
        expression=exp.column(rel.to.column, table=rel.to.table, quoted=True),
    )


def _join_kind(rel: RelationshipDef) -> str:
    return "left" if rel.join_type == "left" else "inner"
