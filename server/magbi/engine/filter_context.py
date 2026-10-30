"""Turn a query ``where`` list into compiler filter tuples.

Page, report, and slicer filters are already flattened into ``where`` by the
caller. Every operator here is one the compiler can replace inside CALCULATE.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from magbi.connectors.types import DataType
from magbi.engine.errors import QueryError
from magbi.engine.semantic import SemanticQuery, _column, _table_name
from magbi.model.schema import DatasetDefinition

_COMPARISON = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}
_ONE_VALUE = frozenset(_COMPARISON) | {"contains", "startsWith"}
_SET = frozenset({"in", "notIn"})
_BLANK = frozenset({"isBlank", "isNotBlank"})


@dataclass(frozen=True, slots=True)
class BoundFilter:
    table: str
    column: str
    op: str
    value: object
    optional: bool = False

    def as_tuple(self) -> tuple[str, str, str, object]:
        return (self.table, self.column, self.op, self.value)


def bind_filters(
    model: DatasetDefinition, query: SemanticQuery
) -> tuple[BoundFilter, ...]:
    """Resolve filter columns and check each operator's values."""
    found: list[BoundFilter] = []
    for item in query.where:
        table = _table_name(model, item.column.table)
        column = _column(model, table, item.column.column)
        op = _COMPARISON.get(item.operator, item.operator)
        value = _value(item.operator, item.values, column.data_type)
        found.append(BoundFilter(table, column.name, op, value, item.optional))
    return tuple(found)


def _value(operator: str, values: list[object] | None, data_type: DataType) -> object:
    given = list(values or [])
    if operator in _BLANK:
        if given:
            raise QueryError("BAD_FILTER", f"{operator} does not take a value")
        return None
    if operator in _ONE_VALUE:
        if len(given) != 1:
            raise QueryError("BAD_FILTER", f"{operator} needs one value")
        if operator in {"contains", "startsWith"} and not isinstance(given[0], str):
            raise QueryError("BAD_FILTER", f"{operator} needs text")
        return _coerce(given[0], data_type)
    if operator in _SET:
        if not given:
            raise QueryError("BAD_FILTER", f"{operator} needs at least one value")
        return tuple(_coerce(value, data_type) for value in given)
    raise QueryError("BAD_FILTER", f"operator {operator!r} is not supported")


def _coerce(value: object, data_type: DataType) -> object:
    if isinstance(value, list | dict):
        raise QueryError("BAD_FILTER", "a filter value must be a single literal")
    if data_type in {DataType.DATE, DataType.DATETIME} and isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            raise QueryError("BAD_FILTER", f"{value!r} is not a date") from None
    return value
