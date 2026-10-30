"""SQL Server connector (pyodbc + Microsoft ODBC Driver 18).

Safety properties:
* ODBC connection-string values are brace-escaped, so a value can never inject
  extra keywords such as ``;Server=evil``.
* SELECTs are generated with sqlglot from catalog metadata with every identifier
  quoted; table names are looked up in the catalog first, never trusted.
* Error messages are scrubbed of driver prefixes and any secret values.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from types import MappingProxyType
from typing import Any, Literal

import pyodbc
import sqlglot
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlglot import exp

from magbi.connectors.base import CastKind, Connector, SourceColumn, SourceTable
from magbi.connectors.errors import ConnectorError, ErrorCode
from magbi.connectors.readonly import check_read_only

DIALECT = "tsql"
DEFAULT_PORT = 1433
_SYSTEM_SCHEMAS = ("sys", "INFORMATION_SCHEMA", "guest")


class SqlServerConfig(BaseModel):
    """Connection settings. ``password`` is kept separate from the stored config."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    authentication: Literal["sql", "integrated"] = "sql"
    username: str | None = Field(default=None, max_length=128)
    password: SecretStr | None = None
    encrypt: bool = True
    trust_server_certificate: bool = False
    connection_timeout: int = Field(default=30, ge=1, le=300)
    query_timeout: int = Field(default=300, ge=0, le=3600)  # 0 = no limit
    driver: str = "ODBC Driver 18 for SQL Server"

    @field_validator("host", "database", "username", "driver")
    @classmethod
    def _no_control_chars(cls, v: str | None) -> str | None:
        if v is not None and any(ord(ch) < 32 for ch in v):
            raise ValueError("must not contain control characters")
        return v

    @model_validator(mode="after")
    def _sql_auth_needs_credentials(self) -> SqlServerConfig:
        if self.authentication == "sql" and (
            not self.username or self.password is None
        ):
            raise ValueError("sql authentication requires username and password")
        return self

    @property
    def server(self) -> str:
        """``host,port``; a named instance (``host\\INSTANCE``) omits the default port."""
        if self.port is not None:
            return f"{self.host},{self.port}"
        if "\\" in self.host:
            return self.host
        return f"{self.host},{DEFAULT_PORT}"


def odbc_value(value: str) -> str:
    """Brace-escape a connection-string value (``}`` is doubled inside braces)."""
    return "{" + value.replace("}", "}}") + "}"


def build_connection_string(cfg: SqlServerConfig) -> str:
    parts = [
        f"DRIVER={odbc_value(cfg.driver)}",
        f"SERVER={odbc_value(cfg.server)}",
        f"DATABASE={odbc_value(cfg.database)}",
        f"Encrypt={'yes' if cfg.encrypt else 'no'}",
        f"TrustServerCertificate={'yes' if cfg.trust_server_certificate else 'no'}",
        "ApplicationIntent=ReadOnly",
        "APP=MagBI",
    ]
    if cfg.authentication == "integrated":
        parts.append("Trusted_Connection=yes")
    else:
        assert cfg.username is not None and cfg.password is not None
        parts.append(f"UID={odbc_value(cfg.username)}")
        parts.append(f"PWD={odbc_value(cfg.password.get_secret_value())}")
    return ";".join(parts)


# -- error handling -----------------------------------------------------------

_PREFIX_RE = re.compile(
    r"\[(?:[0-9A-Z]{5}|Microsoft|ODBC Driver[^\]]*|SQL Server|ODBC SQL Server Driver)\]\s*"
)
_SUFFIX_RE = re.compile(r"(?:\s*\((?:\d+|SQL[A-Za-z]+)\))+\s*$")
_PWD_RE = re.compile(r"(PWD=)(\{[^}]*(?:\}\}[^}]*)*\}|[^;]*)", re.IGNORECASE)


def scrub_message(message: str, secrets: tuple[str, ...] = ()) -> str:
    text = _PWD_RE.sub(r"\1***", message)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    text = _PREFIX_RE.sub("", text)
    text = _SUFFIX_RE.sub("", text)
    return text.strip() or "database error"


def map_error(exc: Exception, secrets: tuple[str, ...] = ()) -> ConnectorError:
    state = ""
    raw = str(exc)
    if isinstance(exc, pyodbc.Error) and exc.args:
        state = str(exc.args[0])
        if len(exc.args) > 1:
            raw = str(exc.args[1])
    message = scrub_message(raw, secrets)
    lowered = message.lower()

    if state == "IM002" or "data source name not found" in lowered:
        return ConnectorError(
            ErrorCode.INVALID_CONFIG, "ODBC driver not found; check the driver name"
        )
    if state == "28000" or "login failed" in lowered:
        return ConnectorError(ErrorCode.AUTH_FAILED, message)
    if "cannot open database" in lowered:
        return ConnectorError(ErrorCode.NOT_FOUND, message)
    if state == "HYT00" or "timeout expired" in lowered or "timed out" in lowered:
        return ConnectorError(ErrorCode.TIMEOUT, message)
    if state in {"08001", "08S01", "08004"} or "tcp provider" in lowered:
        return ConnectorError(ErrorCode.UNREACHABLE, message)
    if state in {"42S02", "42S22"} or "invalid object name" in lowered:
        return ConnectorError(ErrorCode.NOT_FOUND, message)
    return ConnectorError(ErrorCode.QUERY_FAILED, message)


# -- SQL generation -----------------------------------------------------------


def _column(name: str) -> exp.Column:
    return exp.column(name, quoted=True)


def _select_expression(column: SourceColumn, cast: CastKind | None) -> exp.Expr:
    col = _column(column.name)
    if cast == "string":
        target = exp.DataType.build("NVARCHAR(MAX)", dialect=DIALECT)
        return exp.alias_(exp.Cast(this=col, to=target), column.name, quoted=True)
    if cast == "utc_datetime":
        shifted = exp.Anonymous(
            this="SWITCHOFFSET", expressions=[col, exp.Literal.number(0)]
        )
        target = exp.DataType.build("DATETIME2(6)", dialect=DIALECT)
        return exp.alias_(exp.Cast(this=shifted, to=target), column.name, quoted=True)
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
    columns = [_select_expression(c, casts.get(c.name)) for c in table.columns]
    query = exp.select(*columns).from_(_table(table))
    if limit is not None:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        query = query.limit(limit)
    return query.sql(dialect=DIALECT)


def _table(table: SourceTable) -> exp.Table:
    return exp.table_(table.name, db=table.schema, quoted=True)


def build_count_sql(table: SourceTable) -> str:
    count = exp.Anonymous(this="COUNT_BIG", expressions=[exp.Star()])
    return exp.select(count).from_(_table(table)).sql(dialect=DIALECT)


_SELECT_ONLY_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def _assert_select(sql: str) -> None:
    if not _SELECT_ONLY_RE.match(sql):
        raise ConnectorError(
            ErrorCode.UNSUPPORTED, "only SELECT statements are allowed"
        )
    parsed = sqlglot.parse(sql, dialect=DIALECT)
    if len(parsed) != 1 or not isinstance(parsed[0], exp.Query):
        raise ConnectorError(
            ErrorCode.UNSUPPORTED, "exactly one SELECT statement is allowed"
        )


# -- catalog queries ----------------------------------------------------------

_SCHEMAS_SQL = """
SELECT DISTINCT s.name
FROM sys.schemas s
JOIN sys.objects o ON o.schema_id = s.schema_id
WHERE o.type IN ('U', 'V') AND o.is_ms_shipped = 0
  AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')
ORDER BY s.name
"""

_DESCRIBE_SQL = """
SELECT name, system_type_name, max_length, precision, scale, is_nullable
FROM sys.dm_exec_describe_first_result_set(?, NULL, 0)
WHERE is_hidden = 0
ORDER BY column_ordinal
"""

_TABLES_SQL = """
SELECT o.object_id, o.name, o.type
FROM sys.objects o
WHERE o.schema_id = SCHEMA_ID(?) AND o.type IN ('U', 'V') AND o.is_ms_shipped = 0
ORDER BY o.name
"""

_COLUMNS_SQL = """
SELECT c.object_id, c.name,
       COALESCE(base.name, t.name) AS type_name,
       c.max_length, c.precision, c.scale, c.is_nullable
FROM sys.columns c
JOIN sys.objects o ON o.object_id = c.object_id
JOIN sys.types t ON t.user_type_id = c.user_type_id
LEFT JOIN sys.types base
       ON base.user_type_id = t.system_type_id AND t.is_user_defined = 1
WHERE o.schema_id = SCHEMA_ID(?) AND o.type IN ('U', 'V') AND o.is_ms_shipped = 0
ORDER BY c.object_id, c.column_id
"""

_PK_SQL = """
SELECT ic.object_id, ic.column_id, c.name
FROM sys.indexes i
JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
JOIN sys.objects o ON o.object_id = i.object_id
WHERE i.is_primary_key = 1 AND o.schema_id = SCHEMA_ID(?)
"""

_ROWS_SQL = """
SELECT ps.object_id, SUM(ps.row_count)
FROM sys.dm_db_partition_stats ps
JOIN sys.objects o ON o.object_id = ps.object_id
WHERE ps.index_id IN (0, 1) AND o.schema_id = SCHEMA_ID(?)
GROUP BY ps.object_id
"""

_NCHAR_TYPES = {"nchar", "nvarchar"}


class SqlServerConnector(Connector):
    def __init__(self) -> None:
        self._conn: pyodbc.Connection | None = None
        self._secrets: tuple[str, ...] = ()
        self._query_timeout = 0

    # -- lifecycle -----------------------------------------------------------

    def connect(self, config: Mapping[str, Any]) -> None:
        try:
            cfg = SqlServerConfig.model_validate(dict(config))
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
            self._conn = pyodbc.connect(
                build_connection_string(cfg),
                timeout=cfg.connection_timeout,
                autocommit=True,
            )
        except pyodbc.Error as exc:
            raise map_error(exc, self._secrets) from None
        self._query_timeout = cfg.query_timeout

    def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except pyodbc.Error:
                pass

    def _connection(self) -> pyodbc.Connection:
        if self._conn is None:
            raise ConnectorError(ErrorCode.NOT_CONNECTED, "not connected")
        return self._conn

    def _fetchall(self, sql: str, *params: Any) -> list[tuple[Any, ...]]:
        conn = self._connection()
        try:
            cursor = conn.cursor()
            try:
                cursor.execute(sql, *params)
                return [tuple(r) for r in cursor.fetchall()]
            finally:
                cursor.close()
        except pyodbc.Error as exc:
            raise map_error(exc, self._secrets) from None

    # -- metadata ------------------------------------------------------------

    def get_server_version(self) -> str:
        rows = self._fetchall("SELECT @@VERSION")
        return str(rows[0][0]).splitlines()[0].strip()

    def list_schemas(self) -> list[str]:
        return [str(r[0]) for r in self._fetchall(_SCHEMAS_SQL)]

    def describe_query(self, sql: str) -> list[SourceColumn]:
        rows = self._fetchall(_DESCRIBE_SQL, check_read_only(sql))
        columns: list[SourceColumn] = []
        for name, system_type, max_length, precision, scale, nullable in rows:
            if not name:
                raise ConnectorError(
                    ErrorCode.INVALID_CONFIG, "every column of the query needs a name"
                )
            type_name = str(system_type).split("(", 1)[0].strip().lower()
            length = int(max_length) if max_length is not None else None
            if length is not None and length > 0 and type_name in _NCHAR_TYPES:
                length //= 2
            columns.append(
                SourceColumn(
                    name=str(name),
                    data_type=type_name,
                    is_nullable=bool(nullable),
                    max_length=length,
                    precision=int(precision) if precision else None,
                    scale=int(scale) if scale is not None else None,
                )
            )
        if not columns:
            raise ConnectorError(ErrorCode.INVALID_CONFIG, "the query returns no columns")
        return columns

    def list_tables(self, schema: str) -> list[SourceTable]:
        tables = self._fetchall(_TABLES_SQL, schema)
        if not tables:
            return []
        columns_by_obj: dict[int, list[SourceColumn]] = {}
        pk_by_obj: dict[int, set[str]] = {}
        for object_id, name in ((r[0], r[2]) for r in self._fetchall(_PK_SQL, schema)):
            pk_by_obj.setdefault(int(object_id), set()).add(str(name))
        for r in self._fetchall(_COLUMNS_SQL, schema):
            object_id, name, type_name, max_length, precision, scale, nullable = r
            type_name = str(type_name).lower()
            length = int(max_length) if max_length is not None else None
            if length is not None and length > 0 and type_name in _NCHAR_TYPES:
                length //= 2  # sys.columns reports bytes
            columns_by_obj.setdefault(int(object_id), []).append(
                SourceColumn(
                    name=str(name),
                    data_type=type_name,
                    is_nullable=bool(nullable),
                    is_primary_key=str(name) in pk_by_obj.get(int(object_id), set()),
                    max_length=length,
                    precision=int(precision) if precision else None,
                    scale=int(scale) if scale is not None else None,
                )
            )
        try:
            rows_by_obj = {
                int(r[0]): int(r[1]) for r in self._fetchall(_ROWS_SQL, schema)
            }
        except ConnectorError:
            rows_by_obj = {}  # needs VIEW DATABASE STATE; estimates are optional

        return [
            SourceTable(
                schema=schema,
                name=str(name),
                columns=columns_by_obj.get(int(object_id), []),
                estimated_rows=rows_by_obj.get(int(object_id)),
                kind="view" if str(kind).strip() == "V" else "table",
            )
            for object_id, name, kind in tables
        ]

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
        conn = self._connection()
        try:
            conn.timeout = self._query_timeout
            cursor = conn.cursor()
        except pyodbc.Error as exc:
            raise map_error(exc, self._secrets) from None
        return self._stream(cursor, sql, batch_size)

    def _stream(
        self, cursor: pyodbc.Cursor, sql: str, batch_size: int
    ) -> Iterator[tuple[Any, ...]]:
        try:
            cursor.execute(sql)
            while True:
                batch = cursor.fetchmany(batch_size)
                if not batch:
                    return
                for row in batch:
                    yield tuple(row)
        except pyodbc.Error as exc:
            raise map_error(exc, self._secrets) from None
        finally:
            cursor.close()
