"""Turn DuckDB rows into the DataShapeResult from ``web/src/types/query.ts``."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from magbi.engine.semantic import DEFAULT_LIMIT, BoundQuery, GroupField, MeasureField


def shape(
    bound: BoundQuery,
    rows: list[tuple[object, ...]],
    totals: tuple[object, ...] | None,
) -> dict[str, object]:
    """Drop all-null measure rows, format cells, and flag a cut-off limit."""
    applied = DEFAULT_LIMIT if bound.limit is None else bound.limit
    truncated = len(rows) > applied
    kept = rows[:applied]
    measure_at = [
        index
        for index, field in enumerate(bound.fields)
        if isinstance(field, MeasureField)
    ]
    visible = [
        row
        for row in kept
        if not measure_at or any(row[index] is not None for index in measure_at)
    ]
    body = [
        [_cell(row[index], field) for index, field in enumerate(bound.fields)]
        for row in visible
    ]
    return {
        "columns": [_column(field) for field in bound.fields],
        "rows": body,
        "rowCount": len(body),
        "totals": None if totals is None else _totals(bound, totals),
        "truncated": truncated,
    }


def _column(field: GroupField | MeasureField) -> dict[str, object]:
    if isinstance(field, GroupField):
        return {
            "name": field.alias,
            "dataType": field.data_type.value,
            "isMeasure": False,
            "format": None,
        }
    return {
        "name": field.alias,
        "dataType": field.data_type.value,
        "isMeasure": True,
        "format": field.format,
    }


def _totals(bound: BoundQuery, values: tuple[object, ...]) -> list[object]:
    cursor = 0
    aligned: list[object] = []
    for field in bound.fields:
        if isinstance(field, GroupField):
            aligned.append(None)
            continue
        aligned.append(_cell(values[cursor], field))
        cursor += 1
    return aligned


def _cell(value: object, field: GroupField | MeasureField) -> object:
    if isinstance(value, dt.datetime):
        return (
            value.date().isoformat()
            if field.data_type.value == "date"
            else value.isoformat()
        )
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value
