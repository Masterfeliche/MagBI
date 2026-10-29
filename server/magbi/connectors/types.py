"""Source type to MagBI/Arrow/DuckDB type mapping (DATASET-MODEL-SPEC 4.1).

Every source column gets a ``TypePlan``. Types we cannot represent are imported
as text rather than dropped, and the plan carries a warning so the refresh
result can tell the user.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

import pyarrow as pa

from magbi.connectors.base import CastKind, SourceColumn

MAX_DECIMAL_PRECISION = 38  # DuckDB DECIMAL limit


class DataType(enum.StrEnum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    BINARY = "binary"


@dataclass(frozen=True)
class TypePlan:
    column: str
    source_type: str
    data_type: DataType
    arrow_type: pa.DataType
    duckdb_type: str
    cast: CastKind | None = None
    warning: str | None = None


_INTEGER = {"tinyint", "smallint", "int", "bigint"}
_FLOAT = {"float", "real"}
_STRING = {"char", "varchar", "nchar", "nvarchar", "text", "ntext", "uniqueidentifier"}
_BINARY = {"binary", "varbinary", "image", "rowversion", "timestamp"}
_NAIVE_DATETIME = {"datetime", "datetime2", "smalldatetime"}


def normalise_type_name(raw: str) -> str:
    """``"NVARCHAR(50)"`` -> ``"nvarchar"``."""
    return re.sub(r"\(.*\)", "", raw).strip().lower()


def _decimal(column: SourceColumn, precision: int, scale: int, *, src: str) -> TypePlan:
    if precision > MAX_DECIMAL_PRECISION:
        return TypePlan(
            column.name,
            src,
            DataType.DECIMAL,
            pa.float64(),
            "DOUBLE",
            warning=(
                f"column {column.name}: precision {precision} exceeds "
                f"{MAX_DECIMAL_PRECISION}, imported as double (precision loss possible)"
            ),
        )
    return TypePlan(
        column.name,
        src,
        DataType.DECIMAL,
        pa.decimal128(precision, scale),
        f"DECIMAL({precision},{scale})",
    )


def plan_sqlserver_column(column: SourceColumn) -> TypePlan:
    src = normalise_type_name(column.data_type)
    name = column.name

    if src in _INTEGER:
        return TypePlan(name, src, DataType.INTEGER, pa.int64(), "BIGINT")
    if src == "bit":
        return TypePlan(name, src, DataType.BOOLEAN, pa.bool_(), "BOOLEAN")
    if src in {"decimal", "numeric"}:
        precision = column.precision if column.precision is not None else 18
        scale = column.scale if column.scale is not None else 0
        return _decimal(column, precision, scale, src=src)
    if src == "money":
        return _decimal(column, 19, 4, src=src)
    if src == "smallmoney":
        return _decimal(column, 10, 4, src=src)
    if src in _FLOAT:
        return TypePlan(name, src, DataType.DECIMAL, pa.float64(), "DOUBLE")
    if src in _STRING:
        return TypePlan(name, src, DataType.STRING, pa.string(), "VARCHAR")
    if src == "date":
        return TypePlan(name, src, DataType.DATE, pa.date32(), "DATE")
    if src in _NAIVE_DATETIME:
        warning = None
        if src == "datetime2" and (column.scale or 0) > 6:
            warning = (
                f"column {name}: datetime2({column.scale}) truncated to microseconds"
            )
        return TypePlan(
            name,
            src,
            DataType.DATETIME,
            pa.timestamp("us"),
            "TIMESTAMP",
            warning=warning,
        )
    if src == "datetimeoffset":
        return TypePlan(
            name,
            src,
            DataType.DATETIME,
            pa.timestamp("us"),
            "TIMESTAMP",
            cast="utc_datetime",
            warning=f"column {name}: datetimeoffset normalised to UTC",
        )
    if src == "time":
        return TypePlan(name, src, DataType.TIME, pa.time64("us"), "TIME")
    if src in _BINARY:
        return TypePlan(name, src, DataType.BINARY, pa.binary(), "BLOB")

    # xml, geography, geometry, hierarchyid, sql_variant, anything new
    return TypePlan(
        name,
        src,
        DataType.STRING,
        pa.string(),
        "VARCHAR",
        cast="string",
        warning=f"column {name}: unsupported type '{src}' imported as text",
    )


def plan_columns(columns: list[SourceColumn]) -> list[TypePlan]:
    return [plan_sqlserver_column(c) for c in columns]


def arrow_schema(plans: list[TypePlan]) -> pa.Schema:
    return pa.schema([pa.field(p.column, p.arrow_type, nullable=True) for p in plans])


def cast_map(plans: list[TypePlan]) -> dict[str, CastKind]:
    return {p.column: p.cast for p in plans if p.cast is not None}


def warnings(plans: list[TypePlan]) -> list[str]:
    return [p.warning for p in plans if p.warning]
