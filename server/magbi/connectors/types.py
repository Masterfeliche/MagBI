"""Source type to MagBI/Arrow/DuckDB type mapping (DATASET-MODEL-SPEC 4.1).

Every source column gets a ``TypePlan``. Types we cannot represent are imported
as text rather than dropped, and the plan carries a warning so the refresh
result can tell the user.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import enum
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import pyarrow as pa

from magbi.connectors.base import CastKind, SourceColumn

MAX_DECIMAL_PRECISION = 38  # DuckDB DECIMAL limit

# How a value from the driver becomes the Arrow type, when the driver doesn't
# already return it (JSON sources send dates and decimals as text).
Coerce = Literal[
    "text",
    "json",
    "date",
    "datetime",
    "time",
    "decimal",
    "float",
    "binary",
    "integer",
    "boolean",
]


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
    coerce: Coerce | None = None


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


def _unsupported(column: SourceColumn, src: str) -> TypePlan:
    return TypePlan(
        column.name,
        src,
        DataType.STRING,
        pa.string(),
        "VARCHAR",
        cast="string",
        warning=f"column {column.name}: unsupported type '{src}' imported as text",
    )


def _text(
    column: SourceColumn, src: str, *, cast: bool = False, note: str | None = None
) -> TypePlan:
    return TypePlan(
        column.name,
        src,
        DataType.STRING,
        pa.string(),
        "VARCHAR",
        cast="string" if cast else None,
        warning=f"column {column.name}: {note}" if note else None,
    )


# -- PostgreSQL ------------------------------------------------------------------

_PG_ALIASES = {
    "int2": "smallint",
    "int4": "integer",
    "int8": "bigint",
    "serial": "integer",
    "bigserial": "bigint",
    "float4": "real",
    "float8": "double precision",
    "bool": "boolean",
    "varchar": "character varying",
    "bpchar": "character",
    "char": "character",
    "decimal": "numeric",
    "timestamp": "timestamp without time zone",
    "timestamptz": "timestamp with time zone",
    "time": "time without time zone",
    "timetz": "time with time zone",
}
_PG_TEXT = {"character varying", "character", "text", "name", "citext"}
# Read as text in the source: no Arrow type fits, but the text means something.
_PG_AS_TEXT = {
    "uuid",
    "json",
    "jsonb",
    "interval",
    "inet",
    "cidr",
    "macaddr",
    "xml",
    "money",
    "time with time zone",
    "user-defined",
    "array",
    "bit",
    "bit varying",
    "tsvector",
    "oid",
    "point",
    "hstore",
}
# Text is the natural form of these, so no warning.
_PG_QUIET_TEXT = {
    "uuid",
    "json",
    "jsonb",
    "user-defined",
    "inet",
    "cidr",
    "macaddr",
    "xml",
}


def plan_postgres_column(column: SourceColumn) -> TypePlan:
    src = normalise_type_name(column.data_type)
    if src.startswith("_") or src.endswith("[]"):
        src = "array"
    src = _PG_ALIASES.get(src, src)
    name = column.name
    if src in {"smallint", "integer", "bigint"}:
        return TypePlan(name, src, DataType.INTEGER, pa.int64(), "BIGINT")
    if src == "boolean":
        return TypePlan(name, src, DataType.BOOLEAN, pa.bool_(), "BOOLEAN")
    if src == "numeric":
        if column.precision:
            return _decimal(column, column.precision, column.scale or 0, src=src)
        return TypePlan(
            name,
            src,
            DataType.DECIMAL,
            pa.float64(),
            "DOUBLE",
            coerce="float",
            warning=f"column {name}: numeric without a precision imported as double",
        )
    if src in {"real", "double precision"}:
        return TypePlan(name, src, DataType.DECIMAL, pa.float64(), "DOUBLE")
    if src in _PG_TEXT:
        return _text(column, src)
    if src == "date":
        return TypePlan(name, src, DataType.DATE, pa.date32(), "DATE")
    if src == "timestamp without time zone":
        return TypePlan(name, src, DataType.DATETIME, pa.timestamp("us"), "TIMESTAMP")
    if src == "timestamp with time zone":
        return TypePlan(
            name,
            src,
            DataType.DATETIME,
            pa.timestamp("us"),
            "TIMESTAMP",
            cast="utc_datetime",
            warning=f"column {name}: timestamp with time zone normalised to UTC",
        )
    if src == "time without time zone":
        return TypePlan(name, src, DataType.TIME, pa.time64("us"), "TIME")
    if src == "bytea":
        return TypePlan(name, src, DataType.BINARY, pa.binary(), "BLOB")
    if src in _PG_AS_TEXT:
        return _text(
            column,
            src,
            cast=True,
            note=None if src in _PG_QUIET_TEXT else f"{src} imported as text",
        )
    return _unsupported(column, src)


# -- MySQL and MariaDB -------------------------------------------------------------

_MY_INTEGER = {"tinyint", "smallint", "mediumint", "int", "integer", "bigint", "year"}
_MY_TEXT = {
    "char",
    "varchar",
    "tinytext",
    "text",
    "mediumtext",
    "longtext",
    "enum",
    "set",
    "json",
}
_MY_BINARY = {"binary", "varbinary", "tinyblob", "blob", "mediumblob", "longblob"}


def plan_mysql_column(column: SourceColumn) -> TypePlan:
    raw = column.data_type.lower()
    unsigned = "unsigned" in raw
    src = normalise_type_name(raw.replace("unsigned", "").replace("zerofill", ""))
    name = column.name
    if src == "bigint" and unsigned:
        return _decimal(column, 20, 0, src="bigint unsigned")
    if src in _MY_INTEGER:
        return TypePlan(name, src, DataType.INTEGER, pa.int64(), "BIGINT")
    if src in {"decimal", "numeric"}:
        return _decimal(column, column.precision or 10, column.scale or 0, src=src)
    if src in {"float", "double", "real"}:
        return TypePlan(name, src, DataType.DECIMAL, pa.float64(), "DOUBLE")
    if src in _MY_TEXT:
        return _text(column, src)
    # MySQL hands back zero dates ('0000-00-00') as text: they become blank.
    if src == "date":
        return TypePlan(name, src, DataType.DATE, pa.date32(), "DATE", coerce="date")
    if src in {"datetime", "timestamp"}:
        return TypePlan(
            name,
            src,
            DataType.DATETIME,
            pa.timestamp("us"),
            "TIMESTAMP",
            coerce="datetime",
        )
    if src == "time":
        return _text(
            column,
            src,
            cast=True,
            note="time imported as text (MySQL times can exceed 24 hours)",
        )
    if src in _MY_BINARY:
        return TypePlan(name, src, DataType.BINARY, pa.binary(), "BLOB")
    if src == "bit":
        return _text(column, src, cast=True, note="bit imported as text")
    return _unsupported(column, src)


# -- OData (Edm types) and REST JSON (types read from the values) ----------------------

_EDM_INTEGER = {
    "edm.byte",
    "edm.sbyte",
    "edm.int16",
    "edm.int32",
    "edm.int64",
    "json.integer",
}


def plan_odata_column(column: SourceColumn) -> TypePlan:
    src = column.data_type.lower()
    name = column.name
    if src in _EDM_INTEGER:
        return TypePlan(
            name, src, DataType.INTEGER, pa.int64(), "BIGINT", coerce="integer"
        )
    if src == "edm.decimal":
        if column.precision:
            plan = _decimal(column, column.precision, column.scale or 0, src=src)
            exact = plan.arrow_type != pa.float64()
            return TypePlan(
                name,
                src,
                plan.data_type,
                plan.arrow_type,
                plan.duckdb_type,
                warning=plan.warning,
                coerce="decimal" if exact else "float",
            )
        return TypePlan(
            name, src, DataType.DECIMAL, pa.float64(), "DOUBLE", coerce="float"
        )
    if src in {"edm.double", "edm.single", "json.number"}:
        return TypePlan(
            name, src, DataType.DECIMAL, pa.float64(), "DOUBLE", coerce="float"
        )
    if src in {"edm.boolean", "json.boolean"}:
        return TypePlan(
            name, src, DataType.BOOLEAN, pa.bool_(), "BOOLEAN", coerce="boolean"
        )
    if src in {"edm.date", "json.date"}:
        return TypePlan(name, src, DataType.DATE, pa.date32(), "DATE", coerce="date")
    if src in {"edm.datetimeoffset", "edm.datetime", "json.datetime"}:
        return TypePlan(
            name,
            src,
            DataType.DATETIME,
            pa.timestamp("us"),
            "TIMESTAMP",
            coerce="datetime",
            warning=f"column {name}: date and time normalised to UTC"
            if src == "edm.datetimeoffset"
            else None,
        )
    if src in {"edm.timeofday", "edm.time"}:
        return TypePlan(
            name, src, DataType.TIME, pa.time64("us"), "TIME", coerce="time"
        )
    if src == "edm.binary":
        return TypePlan(
            name, src, DataType.BINARY, pa.binary(), "BLOB", coerce="binary"
        )
    if src in {"edm.string", "edm.guid", "edm.duration", "json.string"}:
        return TypePlan(
            name, src, DataType.STRING, pa.string(), "VARCHAR", coerce="text"
        )
    # Collections, geography, nested objects and anything unknown are kept as JSON text.
    quiet = src in {"json.object", "json.array"} or src.startswith("collection(")
    return TypePlan(
        name,
        src,
        DataType.STRING,
        pa.string(),
        "VARCHAR",
        coerce="json",
        warning=None if quiet else f"column {name}: type '{src}' imported as JSON text",
    )


_PLANNERS: dict[str, Callable[[SourceColumn], TypePlan]] = {
    "tsql": plan_sqlserver_column,
    "postgres": plan_postgres_column,
    "mysql": plan_mysql_column,
    "odata": plan_odata_column,
}


def plan_columns(columns: list[SourceColumn], dialect: str = "tsql") -> list[TypePlan]:
    """Plan each column from the source's own type names (``Connector.get_dialect()``)."""
    planner = _PLANNERS.get(dialect, plan_sqlserver_column)
    return [planner(c) for c in columns]


# -- value coercion ------------------------------------------------------------------

_MS_DATE = re.compile(r"^/Date\((-?\d+)(?:[+-]\d{4})?\)/$")  # OData v2
_DURATION = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?")


def _utc_naive(value: dt.datetime) -> dt.datetime:
    return value.astimezone(dt.UTC).replace(tzinfo=None) if value.tzinfo else value


def _to_datetime(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return _utc_naive(value)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day)
    if not isinstance(value, str) or not value or value.startswith("0000"):
        return None
    legacy = _MS_DATE.match(value)
    if legacy:
        return dt.datetime(1970, 1, 1) + dt.timedelta(milliseconds=int(legacy.group(1)))
    return _utc_naive(dt.datetime.fromisoformat(value))


def _to_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    stamp = _to_datetime(value)
    return stamp.date() if stamp else None


def _to_time(value: Any) -> dt.time | None:
    if value is None or isinstance(value, dt.time):
        return value
    if isinstance(value, dt.timedelta):
        return (dt.datetime(2000, 1, 1) + value).time()
    text = str(value)
    duration = _DURATION.fullmatch(text)  # OData v2 Edm.Time is a duration
    if duration:
        hours, minutes, seconds = (float(part or 0) for part in duration.groups())
        return (
            dt.datetime(2000, 1, 1)
            + dt.timedelta(hours=hours, minutes=minutes, seconds=seconds)
        ).time()
    return dt.time.fromisoformat(text) if text else None


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ValueError("not a number") from None


def _to_float(value: Any) -> float | None:
    return None if value is None or value == "" else float(value)


def _to_int(value: Any) -> int | None:
    return None if value is None or value == "" else int(value)


def _to_bool(value: Any) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _to_binary(value: Any) -> bytes | None:
    if value is None or isinstance(value, bytes):
        return value
    try:
        return base64.b64decode(str(value))
    except (binascii.Error, ValueError):
        raise ValueError("not base64") from None


def _to_json(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _to_text(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return _to_json(value)
    return str(value)


_COERCERS: dict[str, Callable[[Any], Any]] = {
    "text": _to_text,
    "json": _to_json,
    "date": _to_date,
    "datetime": _to_datetime,
    "time": _to_time,
    "decimal": _to_decimal,
    "float": _to_float,
    "binary": _to_binary,
    "integer": _to_int,
    "boolean": _to_bool,
}


def coercer_for(plan: TypePlan) -> Callable[[Any], Any] | None:
    """The function that turns a driver value into the plan's Arrow type, when one is needed."""
    return _COERCERS[plan.coerce] if plan.coerce is not None else None


def arrow_schema(plans: list[TypePlan]) -> pa.Schema:
    return pa.schema([pa.field(p.column, p.arrow_type, nullable=True) for p in plans])


def cast_map(plans: list[TypePlan]) -> dict[str, CastKind]:
    return {p.column: p.cast for p in plans if p.cast is not None}


def warnings(plans: list[TypePlan]) -> list[str]:
    return [p.warning for p in plans if p.warning]
