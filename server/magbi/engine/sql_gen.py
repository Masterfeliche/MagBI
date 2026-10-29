"""Assemble one DuckDB statement for a bound query.

One home table is one SELECT. Two home tables are grouped subqueries combined
with FULL OUTER JOIN on the group columns, so neither fact inflates the other.
"""

from __future__ import annotations

from typing import cast

from sqlglot import exp

from magbi.engine.filter_context import BoundFilter
from magbi.engine.grouping import FactGroup, fact_groups
from magbi.engine.joins import join_steps
from magbi.engine.semantic import BoundQuery, GroupField
from magbi.model.schema import DatasetDefinition, RelationshipDef


def detail_sql(
    model: DatasetDefinition,
    bound: BoundQuery,
    filters: tuple[BoundFilter, ...] = (),
) -> str:
    """SQL for the detail rows. Filters are already inside each aggregate."""
    groups = fact_groups(model, bound, filters)
    if len(groups) == 1:
        return _one_fact(model, bound, groups[0]).sql(dialect="duckdb")
    parts = [
        _one_fact(model, bound, group).subquery(alias=f"q{index}")
        for index, group in enumerate(groups)
    ]
    owners = {
        measure.alias: index
        for index, group in enumerate(groups)
        for measure, _plan in group.measures
    }
    query = exp.select(*_outer(bound, len(groups), owners)).from_(parts[0])
    for index, part in enumerate(parts[1:], start=1):
        if bound.groups:
            query = query.join(part, on=_keys(bound.groups, index), join_type="full")
        else:
            query = query.join(part, join_type="cross")
    return query.sql(dialect="duckdb")


def _one_fact(
    model: DatasetDefinition, bound: BoundQuery, group: FactGroup
) -> exp.Select:
    selected: list[exp.Expression] = [
        cast(
            exp.Expression,
            _quoted(field.column, field.table).as_(field.alias, quoted=True),
        )
        for field in bound.groups
    ]
    needed = [field.table for field in bound.groups]
    for measure, plan in group.measures:
        selected.append(
            cast(exp.Expression, plan.expression.copy().as_(measure.alias, quoted=True))
        )
        needed.extend(plan.tables)
    query = exp.select(*selected).from_(_table(group.fact))
    for rel, nxt in join_steps(model, group.fact, tuple(needed)):
        query = query.join(_table(nxt), on=_on(rel), join_type=_join_kind(rel))
    if bound.groups:
        query = query.group_by(
            *[
                cast(exp.Expression, _quoted(field.column, field.table))
                for field in bound.groups
            ]
        )
    return query


def _outer(
    bound: BoundQuery, count: int, owners: dict[str, int]
) -> list[exp.Expression]:
    selected: list[exp.Expression] = []
    for field in bound.groups:
        parts = [_quoted(field.alias, f"q{index}") for index in range(count)]
        merged: exp.Expression = parts[0]
        if len(parts) > 1:
            merged = cast(
                exp.Expression, exp.Coalesce(this=parts[0], expressions=parts[1:])
            )
        selected.append(cast(exp.Expression, merged.as_(field.alias, quoted=True)))
    for measure in bound.measures:
        selected.append(_quoted(measure.alias, f"q{owners[measure.alias]}"))
    return selected


def _keys(groups: tuple[GroupField, ...], index: int) -> exp.Expression:
    terms: list[exp.Expression] = []
    for field in groups:
        right = _quoted(field.alias, f"q{index}")
        if index == 1:
            left: exp.Expression = _quoted(field.alias, "q0")
        else:
            previous = [_quoted(field.alias, f"q{earlier}") for earlier in range(index)]
            left = exp.Coalesce(this=previous[0], expressions=previous[1:])
        terms.append(exp.NullSafeEQ(this=left, expression=right))
    combined = terms[0]
    for term in terms[1:]:
        combined = exp.And(this=combined, expression=term)
    return combined


def _quoted(column: str, table: str) -> exp.Column:
    return exp.column(column, table=table, quoted=True)


def _table(name: str) -> exp.Table:
    return exp.table_(name, quoted=True)


def _on(rel: RelationshipDef) -> exp.Expression:
    return exp.EQ(
        this=exp.column(rel.from_.column, table=rel.from_.table, quoted=True),
        expression=exp.column(rel.to.column, table=rel.to.table, quoted=True),
    )


def _join_kind(rel: RelationshipDef) -> str:
    return "left" if rel.join_type == "left" else "inner"
