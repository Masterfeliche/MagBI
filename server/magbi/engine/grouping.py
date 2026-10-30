"""Group measures by the fact table they aggregate.

Two facts in one visual become two subqueries. One measure that aggregates
two facts is still rejected by the compiler.

A filter reaches a fact only along single-direction relationships, from the
one side to the many side. A filter that cannot reach a fact leaves that fact
unfiltered, as in Power BI, and is reported so the visual can say so.
"""

from __future__ import annotations

from dataclasses import dataclass

from magbi.dax.compiler import AggregatePlan, compile_aggregate
from magbi.dax.errors import DaxError
from magbi.engine.errors import QueryError
from magbi.engine.filter_context import BoundFilter
from magbi.engine.semantic import BoundQuery, MeasureField
from magbi.model.relationships import join_path
from magbi.model.schema import DatasetDefinition, ModelSchemaError

FilterTuple = tuple[str, str, str, object]


@dataclass(frozen=True, slots=True)
class FactGroup:
    fact: str
    measures: tuple[tuple[MeasureField, AggregatePlan], ...]
    filters: tuple[FilterTuple, ...] = ()
    ignored: tuple[str, ...] = ()


def fact_groups(
    model: DatasetDefinition,
    bound: BoundQuery,
    filters: tuple[BoundFilter, ...] = (),
) -> tuple[FactGroup, ...]:
    """One group per home table, in the order the measures appear."""
    if not bound.measures:
        fact = bound.sources[0] if bound.sources else bound.groups[0].table
        kept, ignored = filters_for_fact(model, fact, filters)
        return (FactGroup(fact, (), kept, ignored),)
    grouped: dict[str, list[tuple[MeasureField, AggregatePlan]]] = {}
    seen: dict[str, tuple[tuple[FilterTuple, ...], tuple[str, ...]]] = {}
    order: list[str] = []
    for measure in bound.measures:
        try:
            fact = compile_aggregate(model, measure.expression).fact
            if fact not in seen:
                seen[fact] = filters_for_fact(model, fact, filters)
            plan = compile_aggregate(model, measure.expression, filters=seen[fact][0])
        except DaxError as exc:
            raise QueryError("DAX", str(exc)) from None
        except ModelSchemaError as exc:
            raise QueryError("NO_RELATIONSHIP", str(exc)) from None
        if plan.fact not in grouped:
            order.append(plan.fact)
            grouped[plan.fact] = []
        grouped[plan.fact].append((measure, plan))
    return tuple(
        FactGroup(fact, tuple(grouped[fact]), seen[fact][0], seen[fact][1])
        for fact in order
    )


def ignored_filters(groups: tuple[FactGroup, ...]) -> list[str]:
    """Filter columns that reached none of the facts, as ``Table[Column]``."""
    names = [set(group.ignored) for group in groups]
    common = set.intersection(*names) if names else set()
    ordered = [name for group in groups for name in group.ignored]
    return [name for name in dict.fromkeys(ordered) if name in common]


def filters_for_fact(
    model: DatasetDefinition, fact: str, filters: tuple[BoundFilter, ...]
) -> tuple[tuple[FilterTuple, ...], tuple[str, ...]]:
    """Filters that flow to ``fact``, and the ones that cannot reach it."""
    kept: list[FilterTuple] = []
    ignored: list[str] = []
    for item in filters:
        if item.table == fact:
            kept.append(item.as_tuple())
            continue
        try:
            join_path(model, fact, item.table, directed=True)
        except ModelSchemaError:
            ignored.append(f"{item.table}[{item.column}]")
            continue
        kept.append(item.as_tuple())
    return tuple(kept), tuple(dict.fromkeys(ignored))
