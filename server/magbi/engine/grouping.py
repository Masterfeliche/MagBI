"""Group measures by the fact table they aggregate.

Two facts in one visual become two subqueries. One measure that aggregates
two facts is still rejected by the compiler.
"""

from __future__ import annotations

from dataclasses import dataclass

from magbi.dax.compiler import AggregatePlan, compile_aggregate
from magbi.dax.errors import DaxError
from magbi.engine.errors import QueryError
from magbi.engine.filter_context import BoundFilter
from magbi.engine.semantic import BoundQuery, MeasureField
from magbi.model.schema import DatasetDefinition


@dataclass(frozen=True, slots=True)
class FactGroup:
    fact: str
    measures: tuple[tuple[MeasureField, AggregatePlan], ...]


def fact_groups(
    model: DatasetDefinition,
    bound: BoundQuery,
    filters: tuple[BoundFilter, ...] = (),
) -> tuple[FactGroup, ...]:
    """One group per home table, in the order the measures appear."""
    if not bound.measures:
        fact = bound.sources[0] if bound.sources else bound.groups[0].table
        return (FactGroup(fact, ()),)
    incoming = tuple(item.as_tuple() for item in filters)
    grouped: dict[str, list[tuple[MeasureField, AggregatePlan]]] = {}
    order: list[str] = []
    for measure in bound.measures:
        try:
            plan = compile_aggregate(model, measure.expression, filters=incoming)
        except DaxError as exc:
            raise QueryError("DAX", str(exc)) from None
        if plan.fact not in grouped:
            order.append(plan.fact)
            grouped[plan.fact] = []
        grouped[plan.fact].append((measure, plan))
    return tuple(FactGroup(fact, tuple(grouped[fact])) for fact in order)
