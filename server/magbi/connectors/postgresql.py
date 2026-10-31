"""PostgreSQL connector (psycopg2).

Safety properties, as for SQL Server:
* Settings are passed to the driver as separate keyword arguments, never pasted
  into a connection string.
* The session is read-only (``default_transaction_read_only``) and every query
  passes the read-only guard; SELECTs are generated with sqlglot from catalog
  metadata with every identifier quoted.
* Rows are streamed with a server-side cursor, never loaded whole.
* Error messages are scrubbed of the password.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from types import MappingProxyType
from typing import Any, Literal

import psycopg2
import psycopg2.extensions
import sqlglot
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)
from sqlglot import exp

from magbi.connectors.base import CastKind, Connector, SourceColumn, SourceTable
from magbi.connectors.errors import ConnectorError, ErrorCode
from magbi.connectors.readonly import check_read_only

DIALECT = "postgres"
DEFAULT_PORT = 5432
_CURSOR = "magbi_stream"


class PostgresConfig(BaseModel):
    """Connection settings. ``password`` is kept separate from the stored config."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=DEFAULT_PORT, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr | None = None
    sslmode: Literal[
        "disable", "allow", "prefer", "require", "verify-ca", "verify-full"
    ] = "prefer"
    connection_timeout: int = Field(default=30, ge=1, le=300)
    query_timeout: int = Field(default=300, ge=0, le=3600)  # 0 = no limit

    @field_validator("host", "database", "username")
    @classmethod
    def _no_control_chars(cls, v: str) -> str:
        if any(ord(ch) < 32 for ch in v):
            raise ValueError("must not contain control characters")
        return v


def connect_kwargs(cfg: PostgresConfig) -> dict[str, Any]:
    """Driver arguments: each value separate, so none can add settings of its own."""
    return {
        "host": cfg.host,
        "port": cfg.port,
        "dbname": cfg.database,
        "user": cfg.username,
        "password": cfg.password.get_secret_value() if cfg.password else None,
        "sslmode": cfg.sslmode,
        "connect_timeout": cfg.connection_timeout,
        "application_name": "MagBI",
        # Read-only at the server, and a time limit per statement (milliseconds).
        "options": f"-c default_transaction_read_only=on -c statement_timeout={cfg.query_timeout * 1000}",
    }


# -- error handling -----------------------------------------------------------

_PREFIX_RE = re.compile(r"^(?:FATAL|ERROR|psycopg2\.[\w.]+):\s*", re.IGNORECASE)
_PASSWORD_RE = re.compile(r"(password=)(\S+)", re.IGNORECASE)


def scrub_message(message: str, secrets: tuple[str, ...] = ()) -> str:
    text = _PASSWORD_RE.sub(r"\1***", message)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return _PREFIX_RE.sub("", first).strip() or "database error"


def map_error(exc: Exception, secrets: tuple[str, ...] = ()) -> ConnectorError:
    state = str(getattr(exc, "pgcode", "") or "")
    message = scrub_message(str(exc), secrets)
    lowered = message.lower()
    if (
        state in {"28P01", "28000"}
        or "password authentication failed" in lowered
        or "no password supplied" in lowered
    ):
        return ConnectorError(ErrorCode.AUTH_FAILED, message)
    if state == "3D000" or ("database" in lowered and "does not exist" in lowered):
        return ConnectorError(ErrorCode.NOT_FOUND, message)
    if state == "57014" or "timeout" in lowered or "timed out" in lowered:
        return ConnectorError(ErrorCode.TIMEOUT, message)
    if state in {"42P01", "42703", "3F000"}:
        return ConnectorError(ErrorCode.NOT_FOUND, message)
    if (
        isinstance(exc, psycopg2.OperationalError)
        or "could not connect" in lowered
        or "could not translate host" in lowered
    ):
        return ConnectorError(ErrorCode.UNREACHABLE, message)
    return ConnectorError(ErrorCode.QUERY_FAILED, message)


# -- SQL generation -----------------------------------------------------------


def _table(table: SourceTable) -> exp.Table:
    return exp.table_(table.name, db=table.schema, quoted=True)


def _select_expression(column: SourceColumn, cast: CastKind | None) -> exp.Expr:
    col = exp.column(column.name, quoted=True)
    if cast == "string":
        return exp.alias_(
            exp.Cast(this=col, to=exp.DataType.build("TEXT")), column.name, quoted=True
        )
    if cast == "utc_datetime":
        shifted = exp.AtTimeZone(this=col, zone=exp.Literal.string("UTC"))
        return exp.alias_(shifted, column.name, quoted=True)
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
SELECT DISTINCT n.nspname
FROM pg_namespace n
JOIN pg_class c ON c.relnamespace = n.oid
WHERE c.relkind IN ('r', 'v', 'm', 'p', 'f')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
  AND n.nspname NOT LIKE 'pg_temp%' AND n.nspname NOT LIKE 'pg_toast_temp%'
  AND has_schema_privilege(n.oid, 'USAGE')
ORDER BY n.nspname
"""

_TABLES_SQL = """
SELECT c.relname, c.relkind, c.reltuples::bigint
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relkind IN ('r', 'v', 'm', 'p', 'f')
  AND NOT c.relispartition
ORDER BY c.relname
"""

_COLUMNS_SQL = """
SELECT c.relname, a.attname, t.typname, format_type(a.atttypid, a.atttypmod),
       NOT a.attnotnull, t.typtype, t.typcategory
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_type t ON t.oid = a.atttypid
WHERE n.nspname = %s AND c.relkind IN ('r', 'v', 'm', 'p', 'f')
  AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum
"""

_PK_SQL = """
SELECT c.relname, a.attname
FROM pg_index i
JOIN pg_class c ON c.oid = i.indrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
WHERE n.nspname = %s AND i.indisprimary
"""

_TYPES_SQL = (
    "SELECT oid, typname, typtype, typcategory FROM pg_type WHERE oid = ANY(%s)"
)

_PRECISION_RE = re.compile(r"\((\d+)(?:\s*,\s*(\d+))?\)")


def _column_type(
    typname: str, formatted: str, typtype: str, category: str
) -> tuple[str, int | None, int | None, int | None]:
    """(type name, max length, precision, scale) from the catalog's description."""
    if category == "A":
        return "array", None, None, None
    if typtype == "e":
        return "user-defined", None, None, None
    if typtype == "d":  # a domain: plan it by the type it's written as
        typname = formatted.split("(", 1)[0]
    match = _PRECISION_RE.search(formatted)
    size = int(match.group(1)) if match else None
    scale = int(match.group(2)) if match and match.group(2) else None
    if typname in {"numeric", "decimal"}:
        return "numeric", None, size, scale if size is not None else None
    return typname, size, None, None


class PostgresConnector(Connector):
    def __init__(self) -> None:
        self._conn: Any = None
        self._secrets: tuple[str, ...] = ()

    # -- lifecycle -----------------------------------------------------------

    def connect(self, config: Mapping[str, Any]) -> None:
        try:
            cfg = PostgresConfig.model_validate(dict(config))
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
            conn = psycopg2.connect(**connect_kwargs(cfg))
            conn.set_session(readonly=True, autocommit=False)
        except psycopg2.Error as exc:
            raise map_error(exc, self._secrets) from None
        self._conn = conn

    def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except psycopg2.Error:
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
                rows = [tuple(r) for r in cursor.fetchall()]
            conn.rollback()  # end the read-only transaction; nothing to keep
            return rows
        except psycopg2.Error as exc:
            self._reset()
            raise map_error(exc, self._secrets) from None

    def _reset(self) -> None:
        try:
            if self._conn is not None:
                self._conn.rollback()
        except psycopg2.Error:
            pass

    # -- metadata ------------------------------------------------------------

    def get_server_version(self) -> str:
        return str(self._fetchall("SELECT version()")[0][0]).split(",")[0].strip()

    def list_schemas(self) -> list[str]:
        return [str(r[0]) for r in self._fetchall(_SCHEMAS_SQL)]

    def list_tables(self, schema: str) -> list[SourceTable]:
        tables = self._fetchall(_TABLES_SQL, schema)
        if not tables:
            return []
        keys: dict[str, set[str]] = {}
        for table, column in self._fetchall(_PK_SQL, schema):
            keys.setdefault(str(table), set()).add(str(column))
        columns: dict[str, list[SourceColumn]] = {}
        for (
            table,
            name,
            typname,
            formatted,
            nullable,
            typtype,
            category,
        ) in self._fetchall(_COLUMNS_SQL, schema):
            type_name, length, precision, scale = _column_type(
                str(typname), str(formatted), str(typtype), str(category)
            )
            columns.setdefault(str(table), []).append(
                SourceColumn(
                    name=str(name),
                    data_type=type_name,
                    is_nullable=bool(nullable),
                    is_primary_key=str(name) in keys.get(str(table), set()),
                    max_length=length,
                    precision=precision,
                    scale=scale,
                )
            )
        return [
            SourceTable(
                schema=schema,
                name=str(name),
                columns=columns.get(str(name), []),
                # reltuples is -1 (or 0) before the first ANALYZE: unknown.
                estimated_rows=int(rows)
                if rows is not None and int(rows) > 0
                else None,
                kind="table" if str(kind) in {"r", "p", "f"} else "view",
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
                oids = sorted({int(col.type_code) for col in description})
                cursor.execute(_TYPES_SQL, (oids,))
                types = {
                    int(oid): (str(name), str(kind), str(cat))
                    for oid, name, kind, cat in cursor.fetchall()
                }
            conn.rollback()
        except psycopg2.Error as exc:
            self._reset()
            raise map_error(exc, self._secrets) from None
        columns: list[SourceColumn] = []
        for col in description:
            if not col.name or col.name == "?column?":
                raise ConnectorError(
                    ErrorCode.INVALID_CONFIG, "every column of the query needs a name"
                )
            name, kind, category = types.get(int(col.type_code), ("unknown", "b", "U"))
            type_name, _, _, _ = _column_type(name, name, kind, category)
            precision = (
                col.precision
                if type_name == "numeric" and col.precision and col.precision > 0
                else None
            )
            columns.append(
                SourceColumn(
                    name=str(col.name),
                    data_type=type_name,
                    precision=precision,
                    scale=col.scale if precision is not None else None,
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
        conn = self._connection()
        return self._stream(conn, sql, batch_size)

    def _stream(
        self, conn: Any, sql: str, batch_size: int
    ) -> Iterator[tuple[Any, ...]]:
        cursor = None
        try:
            # A named cursor keeps the result on the server and sends it in batches.
            cursor = conn.cursor(name=_CURSOR)
            cursor.itersize = batch_size
            cursor.execute(sql)
            while True:
                batch = cursor.fetchmany(batch_size)
                if not batch:
                    return
                for row in batch:
                    yield tuple(row)
        except psycopg2.Error as exc:
            raise map_error(exc, self._secrets) from None
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except psycopg2.Error:
                    pass
            self._reset()
