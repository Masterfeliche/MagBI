"""Write an auto-generated date table into a staging file and relate date columns to it.

The first date column on a table gets the active relationship. Further date
columns on the same table are stored inactive, because only one active
relationship is allowed between two tables.
"""

from __future__ import annotations

import datetime as dt
import time

import duckdb
import pyarrow as pa

from magbi.connectors.types import DataType
from magbi.model.date_table import generate_date_table, with_padding
from magbi.model.schema import (
    DatasetDefinition,
    ModelSchemaError,
    RelationshipDef,
    TableDef,
)
from magbi.refresh.importer import ImportPipelineError, TableResult, quote_ident

DATE_TABLE = "Date"
_DATE_TYPES = {DataType.DATE, DataType.DATETIME}
_DUCKDB = {
    DataType.DATE: "DATE",
    DataType.INTEGER: "BIGINT",
    DataType.STRING: "VARCHAR",
    DataType.BOOLEAN: "BOOLEAN",
}
_ARROW = {
    DataType.DATE: pa.date32(),
    DataType.INTEGER: pa.int64(),
    DataType.STRING: pa.string(),
    DataType.BOOLEAN: pa.bool_(),
}


def attach_date_table(
    staging: duckdb.DuckDBPyConnection, definition: DatasetDefinition
) -> tuple[TableResult | None, DatasetDefinition]:
    """Add the date dimension when ``definition.date_table.auto_generate`` is set.

    Returns the import result for that table (a warning and no table when there
    is nothing to cover) and the definition to store. The input is not mutated.
    """
    if not definition.date_table.auto_generate:
        return None, definition
    started = time.perf_counter()
    columns = _date_columns(definition)
    if not columns:
        return _skipped(started, "no date or datetime columns in the model"), definition
    bounds = _bounds(staging, columns)
    if bounds is None:
        return _skipped(
            started, "date columns are present but every value is null"
        ), definition

    start, end = with_padding(*bounds)
    try:
        generated = generate_date_table(
            start, end, definition.date_table, name=DATE_TABLE
        )
    except ModelSchemaError as exc:
        raise ImportPipelineError(str(exc)) from exc
    _write(staging, generated.table, generated.rows)
    updated = _with_date_table(definition, generated.table, columns)
    return (
        TableResult(
            schema="",
            name=DATE_TABLE,
            target=DATE_TABLE,
            rows=len(generated.rows),
            seconds=time.perf_counter() - started,
        ),
        updated,
    )


def _date_columns(definition: DatasetDefinition) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for table in definition.tables:
        if table.is_date_table or table.name == DATE_TABLE:
            continue
        for column in table.columns:
            if column.data_type in _DATE_TYPES:
                found.append((table.name, column.name))
    return found


def _bounds(
    staging: duckdb.DuckDBPyConnection, columns: list[tuple[str, str]]
) -> tuple[dt.date, dt.date] | None:
    lows: list[dt.date] = []
    highs: list[dt.date] = []
    for table, column in columns:
        row = staging.execute(
            f"SELECT MIN({quote_ident(column)}), MAX({quote_ident(column)}) "
            f"FROM {quote_ident(table)}"
        ).fetchone()
        if row is None or row[0] is None or row[1] is None:
            continue
        lows.append(_as_date(row[0]))
        highs.append(_as_date(row[1]))
    if not lows:
        return None
    return min(lows), max(highs)


def _as_date(value: object) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    raise TypeError(f"cannot read a date from {type(value).__name__}")


def _write(
    staging: duckdb.DuckDBPyConnection, table: TableDef, rows: list[dict[str, object]]
) -> None:
    target = quote_ident(table.name)
    columns_sql = ", ".join(
        f"{quote_ident(column.name)} {_DUCKDB[column.data_type]}"
        for column in table.columns
    )
    staging.execute(f"CREATE OR REPLACE TABLE {target} ({columns_sql})")
    arrays = [
        pa.array([row[column.name] for row in rows], type=_ARROW[column.data_type])
        for column in table.columns
    ]
    batch = pa.Table.from_arrays(
        arrays, names=[column.name for column in table.columns]
    )
    staging.register("_magbi_batch", batch)
    try:
        staging.execute(f"INSERT INTO {target} SELECT * FROM _magbi_batch")
    finally:
        staging.unregister("_magbi_batch")


def _with_date_table(
    definition: DatasetDefinition,
    date_table: TableDef,
    columns: list[tuple[str, str]],
) -> DatasetDefinition:
    payload = definition.model_dump(mode="json", by_alias=True)
    payload["tables"] = [t for t in payload["tables"] if t["name"] != date_table.name]
    payload["tables"].append(date_table.model_dump(mode="json", by_alias=True))
    known = {
        (rel["from"]["table"], rel["from"]["column"])
        for rel in payload["relationships"]
        if rel["to"]["table"] == date_table.name
    }
    active = {
        frozenset((rel["from"]["table"], rel["to"]["table"]))
        for rel in payload["relationships"]
        if rel["is_active"]
    }
    for table, column in columns:
        if (table, column) in known:
            continue
        pair = frozenset((table, date_table.name))
        relationship = RelationshipDef.model_validate(
            {
                "from": {"table": table, "column": column},
                "to": {"table": date_table.name, "column": "Date"},
                "cardinality": "many-to-one",
                "is_active": pair not in active,
                "join_type": "left",
            }
        )
        if relationship.is_active:
            active.add(pair)
        payload["relationships"].append(
            relationship.model_dump(mode="json", by_alias=True)
        )
    return DatasetDefinition.model_validate(payload)


def _skipped(started: float, reason: str) -> TableResult:
    return TableResult(
        schema="",
        name=DATE_TABLE,
        target=DATE_TABLE,
        rows=0,
        seconds=time.perf_counter() - started,
        warnings=[f"date table not generated: {reason}"],
    )
