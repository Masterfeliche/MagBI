"""MySQL and MariaDB connector (PyMySQL).

Safety properties, as for SQL Server and PostgreSQL:
* Settings go to the driver as separate arguments, never into a string.
* The session is read-only and every query passes the read-only guard; SELECTs
  are generated with sqlglot from catalog metadata with identifiers quoted.
* Rows are streamed with an unbuffered cursor, never loaded whole.
* The session time zone is UTC, so TIMESTAMP columns arrive as UTC.
* Error messages are scrubbed of the password.

In MySQL a schema is a database: ``list_schemas`` lists the databases the login
can see, and ``database`` in the settings only picks the one to open first.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from types import MappingProxyType
from typing import Any

import pymysql
import pymysql.cursors
import sqlglot
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)
from pymysql.constants import FIELD_TYPE
from sqlglot import exp

from magbi.connectors.base import CastKind, Connector, SourceColumn, SourceTable
from magbi.connectors.errors import ConnectorError, ErrorCode
from magbi.connectors.readonly import check_read_only

DIALECT = "mysql"
DEFAULT_PORT = 3306


class MySqlConfig(BaseModel):
    """Connection settings. ``password`` is kept separate from the stored config."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=DEFAULT_PORT, ge=1, le=65535)
    database: str | None = Field(default=None, max_length=64)
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr | None = None
    ssl: bool = False
    connection_timeout: int = Field(default=30, ge=1, le=300)
    query_timeout: int = Field(default=300, ge=0, le=3600)  # 0 = no limit

    @field_validator("host", "database", "username")
    @classmethod
    def _no_control_chars(cls, v: str | None) -> str | None:
        if v is not None and any(ord(ch) < 32 for ch in v):
            raise ValueError("must not contain control characters")
        return v


def connect_kwargs(cfg: MySqlConfig) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "host": cfg.host,
        "port": cfg.port,
        "user": cfg.username,
        "password": cfg.password.get_secret_value() if cfg.password else "",
        "database": cfg.database or None,
        "charset": "utf8mb4",
        "connect_timeout": cfg.connection_timeout,
        "read_timeout": cfg.query_timeout or None,
        "autocommit": True,
        "program_name": "MagBI",
    }
    if cfg.ssl:
        kwargs["ssl"] = {"check_hostname": True}
    return kwargs


# Session settings run after connecting. A server that lacks one (MariaDB names
# the time limit differently) skips it.
def _session_statements(query_timeout: int) -> list[str]:
    return [
        "SET SESSION TRANSACTION READ ONLY",
        "SET SESSION time_zone = '+00:00'",
        f"SET SESSION max_execution_time = {int(query_timeout) * 1000}",  # MySQL, milliseconds
        f"SET SESSION max_statement_time = {int(query_timeout)}",  # MariaDB, seconds
    ]


# -- error handling -----------------------------------------------------------


def scrub_message(message: str, secrets: tuple[str, ...] = ()) -> str:
    text = message
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    # PyMySQL errors read like (1045, "Access denied for user ...").
    match = re.match(r"^\(\d+,\s*[\"'](.*)[\"']\)$", text.strip(), re.DOTALL)
    if match:
        text = match.group(1)
    return text.strip() or "database error"


def map_error(exc: Exception, secrets: tuple[str, ...] = ()) -> ConnectorError:
    code = int(exc.args[0]) if exc.args and isinstance(exc.args[0], int) else 0
    raw = str(exc.args[1]) if len(exc.args) > 1 else str(exc)
    message = scrub_message(raw, secrets)
    lowered = message.lower()
    if code in {1045, 1044, 1698} or "access denied" in lowered:
        return ConnectorError(ErrorCode.AUTH_FAILED, message)
    if code in {1049, 1146, 1054}:
        return ConnectorError(ErrorCode.NOT_FOUND, message)
    if (
        code in {3024, 1969}
        or "timeout" in lowered
        or "timed out" in lowered
        or "max_execution_time" in lowered
    ):
        return ConnectorError(ErrorCode.TIMEOUT, message)
    if code in {2003, 2005, 2006, 2013} or "can't connect" in lowered:
        return ConnectorError(ErrorCode.UNREACHABLE, message)
    return ConnectorError(ErrorCode.QUERY_FAILED, message)


# -- SQL generation -----------------------------------------------------------


def _table(table: SourceTable) -> exp.Table:
    return exp.table_(table.name, db=table.schema, quoted=True)


def _select_expression(column: SourceColumn, cast: CastKind | None) -> exp.Expr:
    col = exp.column(column.name, quoted=True)
    if cast is not None:  # MySQL has no time-zone type, so every cast is to text
        return exp.alias_(
            exp.Cast(this=col, to=exp.DataType.build("CHAR")), column.name, quoted=True
        )
    return col


def build_select_sql(
    table: SourceTable,
    casts: Mapping[str, CastKind] = MappingProxyType({}),
    limit: int | None = None,
) -> str:
    if not table.columns:
        raise ConnectorError(
            ErrorCode.UNSUPPORTED, f"{table.qualified_name} has no columns"
        )
    query = exp.select(
        *(_select_expression(c, casts.get(c.name)) for c in table.columns)
    ).from_(_table(table))
    if limit is not None:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        query = query.limit(limit)
    return query.sql(dialect=DIALECT)


def build_count_sql(table: SourceTable) -> str:
    return (
        exp.select(exp.Count(this=exp.Star())).from_(_table(table)).sql(dialect=DIALECT)
    )


def _assert_select(sql: str) -> None:
    check_read_only(sql)
    parsed = sqlglot.parse(sql, dialect=DIALECT)
    if len(parsed) != 1 or not isinstance(parsed[0], exp.Query):
        raise ConnectorError(
            ErrorCode.UNSUPPORTED, "exactly one SELECT statement is allowed"
        )


# -- catalog queries ----------------------------------------------------------

_SCHEMAS_SQL = """
SELECT SCHEMA_NAME FROM information_schema.SCHEMATA
WHERE SCHEMA_NAME NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
ORDER BY SCHEMA_NAME
"""

_TABLES_SQL = """
SELECT TABLE_NAME, TABLE_TYPE, TABLE_ROWS FROM information_schema.TABLES
WHERE TABLE_SCHEMA = %s AND TABLE_TYPE IN ('BASE TABLE', 'VIEW', 'SYSTEM VERSIONED')
ORDER BY TABLE_NAME
"""

_COLUMNS_SQL = """
SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY,
       CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = %s
ORDER BY TABLE_NAME, ORDINAL_POSITION
"""

# Result-set type codes, for describing a query. TEXT and BLOB share codes, so
# both read as text; PyMySQL returns text for them on a utf8mb4 connection.
_FIELD_TYPES = {
    FIELD_TYPE.DECIMAL: "decimal",
    FIELD_TYPE.NEWDECIMAL: "decimal",
    FIELD_TYPE.TINY: "tinyint",
    FIELD_TYPE.SHORT: "smallint",
    FIELD_TYPE.LONG: "int",
    FIELD_TYPE.INT24: "mediumint",
    FIELD_TYPE.LONGLONG: "bigint",
    FIELD_TYPE.FLOAT: "float",
    FIELD_TYPE.DOUBLE: "double",
    FIELD_TYPE.DATE: "date",
    FIELD_TYPE.NEWDATE: "date",
    FIELD_TYPE.DATETIME: "datetime",
    FIELD_TYPE.TIMESTAMP: "timestamp",
    FIELD_TYPE.TIME: "time",
    FIELD_TYPE.YEAR: "year",
    FIELD_TYPE.VARCHAR: "varchar",
    FIELD_TYPE.VAR_STRING: "varchar",
    FIELD_TYPE.STRING: "char",
    FIELD_TYPE.ENUM: "enum",
    FIELD_TYPE.SET: "set",
    FIELD_TYPE.JSON: "json",
    FIELD_TYPE.BIT: "bit",
    FIELD_TYPE.TINY_BLOB: "text",
    FIELD_TYPE.MEDIUM_BLOB: "text",
    FIELD_TYPE.LONG_BLOB: "text",
    FIELD_TYPE.BLOB: "text",
    FIELD_TYPE.GEOMETRY: "geometry",
}


class MySqlConnector(Connector):
    def __init__(self) -> None:
        self._conn: Any = None
        self._secrets: tuple[str, ...] = ()

    # -- lifecycle -----------------------------------------------------------

    def connect(self, config: Mapping[str, Any]) -> None:
        try:
            cfg = MySqlConfig.model_validate(dict(config))
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'config'}: {e['msg']}"
                for e in exc.errors()
            )
            raise ConnectorError(ErrorCode.INVALID_CONFIG, problems) from None
        self.close()
        secret = cfg.password.get_secret_value() if cfg.password else ""
        self._secrets = (secret,) if secret else ()
        try:
            conn = pymysql.connect(**connect_kwargs(cfg))
        except pymysql.MySQLError as exc:
            raise map_error(exc, self._secrets) from None
        self._conn = conn
        for statement in _session_statements(cfg.query_timeout):
            try:
                with conn.cursor() as cursor:
                    cursor.execute(statement)
            except pymysql.MySQLError as exc:
                if statement.startswith("SET SESSION TRANSACTION READ ONLY"):
                    self.close()
                    raise map_error(exc, self._secrets) from None
                # A time limit the server doesn't know: the other one applies.

    def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except pymysql.MySQLError:
                pass

    def _connection(self) -> Any:
        if self._conn is None:
            raise ConnectorError(ErrorCode.NOT_CONNECTED, "not connected")
        return self._conn

    def _fetchall(self, sql: str, *params: Any) -> list[tuple[Any, ...]]:
        conn = self._connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params or None)
                return [tuple(r) for r in cursor.fetchall()]
        except pymysql.MySQLError as exc:
            raise map_error(exc, self._secrets) from None

    # -- metadata ------------------------------------------------------------

    def get_server_version(self) -> str:
        version = str(self._fetchall("SELECT VERSION()")[0][0])
        return f"{'MariaDB' if 'mariadb' in version.lower() else 'MySQL'} {version.split('-')[0]}"

    def list_schemas(self) -> list[str]:
        return [str(r[0]) for r in self._fetchall(_SCHEMAS_SQL)]

    def list_tables(self, schema: str) -> list[SourceTable]:
        tables = self._fetchall(_TABLES_SQL, schema)
        if not tables:
            return []
        columns: dict[str, list[SourceColumn]] = {}
        for (
            table,
            name,
            data_type,
            column_type,
            nullable,
            key,
            length,
            precision,
            scale,
        ) in self._fetchall(_COLUMNS_SQL, schema):
            type_name = str(data_type).lower()
            if "unsigned" in str(column_type).lower():
                type_name += " unsigned"
            columns.setdefault(str(table), []).append(
                SourceColumn(
                    name=str(name),
                    data_type=type_name,
                    is_nullable=str(nullable).upper() == "YES",
                    is_primary_key=str(key).upper() == "PRI",
                    max_length=int(length)
                    if length is not None and int(length) < 2**31
                    else None,
                    precision=int(precision) if precision is not None else None,
                    scale=int(scale) if scale is not None else None,
                )
            )
        return [
            SourceTable(
                schema=schema,
                name=str(name),
                columns=columns.get(str(name), []),
                estimated_rows=int(rows) if rows is not None else None,
                kind="view" if str(kind).upper() == "VIEW" else "table",
            )
            for name, kind, rows in tables
        ]

    def describe_query(self, sql: str) -> list[SourceColumn]:
        checked = check_read_only(sql)
        conn = self._connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT * FROM ({checked}) AS magbi_query LIMIT 0")
                description = list(cursor.description or [])
        except pymysql.MySQLError as exc:
            raise map_error(exc, self._secrets) from None
        columns = []
        for name, type_code, _display, _size, precision, scale, nullable in description:
            type_name = _FIELD_TYPES.get(type_code, "unknown")
            columns.append(
                SourceColumn(
                    name=str(name),
                    data_type=type_name,
                    is_nullable=bool(nullable),
                    precision=int(precision)
                    if type_name == "decimal" and precision
                    else None,
                    scale=int(scale)
                    if type_name == "decimal" and scale is not None
                    else None,
                )
            )
        if not columns:
            raise ConnectorError(
                ErrorCode.INVALID_CONFIG, "the query returns no columns"
            )
        return columns

    # -- data ----------------------------------------------------------------

    def get_dialect(self) -> str:
        return DIALECT

    def build_select(
        self,
        table: SourceTable,
        *,
        casts: Mapping[str, CastKind] = MappingProxyType({}),
        limit: int | None = None,
    ) -> str:
        return build_select_sql(table, casts, limit)

    def get_row_count(self, schema: str, table: str) -> int:
        found = self.find_table(schema, table)
        return int(self._fetchall(build_count_sql(found))[0][0])

    def execute_query(
        self, sql: str, *, batch_size: int = 10_000
    ) -> Iterator[tuple[Any, ...]]:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        _assert_select(sql)
        return self._stream(self._connection(), sql, batch_size)

    def _stream(
        self, conn: Any, sql: str, batch_size: int
    ) -> Iterator[tuple[Any, ...]]:
        cursor = None
        try:
            cursor = conn.cursor(
                pymysql.cursors.SSCursor
            )  # unbuffered: rows arrive as they are read
            cursor.execute(sql)
            while True:
                batch = cursor.fetchmany(batch_size)
                if not batch:
                    return
                for row in batch:
                    yield tuple(row)
        except pymysql.MySQLError as exc:
            raise map_error(exc, self._secrets) from None
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except pymysql.MySQLError:
                    pass
