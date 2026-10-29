"""Run the steps that do not fold, then fold whatever comes after them.

Preview reads at most 201 rows from DuckDB. ``fillDown`` sees that order, so a
folded ``sortRows`` is the order that fills.
"""

from __future__ import annotations

from typing import Any

from magbi.transforms.errors import TransformError
from magbi.transforms.folding import fold
from magbi.transforms.steps import (
    FillDownStep,
    PivotStep,
    TransformStep,
    UnpivotStep,
)

PREVIEW_LIMIT = 200


def preview(
    con: Any,
    table: str,
    columns: tuple[str, ...],
    steps: tuple[TransformStep, ...],
) -> dict[str, Any]:
    """Execute ``steps`` and return at most 200 rows plus the fold boundary."""
    pending = steps
    source = table
    names = columns
    rows: list[tuple[Any, ...]] | None = None
    folded_count = 0
    boundary: int | None = None
    sql = ""
    while pending:
        folded = fold(source, names, pending)
        sql = folded.sql if not sql else sql
        fetched = _read(con, folded)
        names = folded.columns
        rows = fetched
        if boundary is None:
            folded_count = folded.folded_count
            boundary = folded.folded_count if folded.remaining else None
        pending = folded.remaining
        if not pending or rows is None:
            break
        step = pending[0]
        names, rows = _python(names, rows, step)
        pending = pending[1:]
        if not pending:
            break
        source = _stage(con, names, rows)
    visible = [] if rows is None else rows
    truncated = len(visible) > PREVIEW_LIMIT
    visible = visible[:PREVIEW_LIMIT]
    return {
        "columns": [{"name": name} for name in names],
        "rows": [list(row) for row in visible],
        "rowCount": len(visible),
        "truncated": truncated,
        "foldedStepCount": folded_count,
        "foldBoundary": boundary,
        "sql": sql,
    }


def _read(con: Any, folded: Any) -> list[tuple[Any, ...]]:
    sql = folded.sql
    if not folded.limited:
        sql = f"SELECT * FROM ({sql}) AS preview_cap LIMIT {PREVIEW_LIMIT + 1}"
    return [tuple(row) for row in con.execute(sql).fetchall()]


def _stage(con: Any, columns: tuple[str, ...], rows: list[tuple[Any, ...]]) -> str:
    con.execute('DROP TABLE IF EXISTS "_preview"')
    quoted = ", ".join(f'"{name}" VARCHAR' for name in columns)
    con.execute(f'CREATE TABLE "_preview" ({quoted})')
    if rows:
        placeholders = ", ".join("?" for _ in columns)
        con.executemany(
            f'INSERT INTO "_preview" VALUES ({placeholders})',
            [
                tuple(str(value) if value is not None else None for value in row)
                for row in rows
            ],
        )
    return "_preview"


def _python(
    columns: tuple[str, ...], rows: list[tuple[Any, ...]], step: TransformStep
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]]:
    index = {name: position for position, name in enumerate(columns)}
    if isinstance(step, FillDownStep):
        for name in step.columns:
            _known(index, name)
        last: dict[str, Any] = {name: None for name in step.columns}
        filled: list[tuple[Any, ...]] = []
        for row in rows:
            mutable = list(row)
            for name in step.columns:
                position = index[name]
                if mutable[position] is None:
                    mutable[position] = last[name]
                else:
                    last[name] = mutable[position]
            filled.append(tuple(mutable))
        return columns, filled
    if isinstance(step, UnpivotStep):
        for name in (*step.id_columns, *step.value_columns):
            _known(index, name)
        melted: list[tuple[Any, ...]] = []
        for row in rows:
            kept = tuple(row[index[name]] for name in step.id_columns)
            for name in step.value_columns:
                melted.append((*kept, name, row[index[name]]))
        return (
            (*step.id_columns, step.attribute_name, step.value_name),
            melted,
        )
    if isinstance(step, PivotStep):
        _known(index, step.key_column)
        _known(index, step.value_column)
        identity = [
            name for name in columns if name not in {step.key_column, step.value_column}
        ]
        keys: list[Any] = []
        seen: set[Any] = set()
        for row in rows:
            key = row[index[step.key_column]]
            if key not in seen:
                seen.add(key)
                keys.append(key)
        buckets: dict[tuple[Any, ...], dict[Any, Any]] = {}
        for row in rows:
            ident = tuple(row[index[name]] for name in identity)
            slot = buckets.setdefault(ident, {})
            key = row[index[step.key_column]]
            slot[key] = _combine(
                step.aggregate, slot.get(key), row[index[step.value_column]]
            )
        pivoted = [
            (*ident, *[slot.get(key) for key in keys])
            for ident, slot in buckets.items()
        ]
        return ((*identity, *[str(key) for key in keys]), pivoted)
    raise TransformError("BAD_STEP", f"{step.type} cannot run after the fold boundary")


def _combine(function: str, current: Any, value: Any) -> Any:
    if function == "count":
        return (0 if current is None else current) + (0 if value is None else 1)
    if value is None:
        return current
    if current is None:
        return value
    if function == "sum":
        return current + value
    if function == "min":
        return min(current, value)
    return max(current, value)


def _known(index: dict[str, int], name: str) -> None:
    if name not in index:
        raise TransformError("UNKNOWN_COLUMN", f"column {name!r} does not exist")
