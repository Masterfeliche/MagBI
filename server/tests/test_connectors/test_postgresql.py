"""PostgreSQL connector against a fake psycopg2 connection (no server needed)."""

from __future__ import annotations

from collections import namedtuple
from typing import Any, Self

import psycopg2
import pytest
from pydantic import ValidationError

from magbi.connectors import postgresql as pg
from magbi.connectors.base import SourceColumn, SourceTable
from magbi.connectors.errors import ConnectorError, ErrorCode
from magbi.connectors.readonly import check_read_only
from magbi.connectors.types import plan_columns

CFG: dict[str, Any] = {
    "host": "db.example.com",
    "database": "erp",
    "username": "bi",
    "password": "S3cret;pw",
}
Col = namedtuple(
    "Col", "name type_code display_size internal_size precision scale null_ok"
)


class FakeCursor:
    def __init__(self, conn: FakeConn, name: str | None = None) -> None:
        self.conn, self.name = conn, name
        self.rows: list[tuple[Any, ...]] = []
        self.description: list[Col] | None = None
        self.closed = False
        self.itersize = 0

    def execute(self, sql: str, params: Any = None) -> None:
        self.conn.executed.append((sql, params, self.name))
        if self.conn.fail_on and self.conn.fail_on in sql:
            raise self.conn.error
        for key, result in self.conn.results.items():
            if key in sql:
                if (
                    isinstance(result, tuple)
                    and len(result) == 2
                    and isinstance(result[0], list)
                    and result[0]
                    and isinstance(result[0][0], Col)
                ):
                    self.description, self.rows = result
                else:
                    self.rows = list(result)
                return
        self.rows = []

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows, self.rows = self.rows, []
        return rows

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        batch, self.rows = self.rows[:size], self.rows[size:]
        self.conn.fetches.append(len(batch))
        return batch

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class FakeConn:
    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.results = results or {}
        self.executed: list[tuple[str, Any, str | None]] = []
        self.fetches: list[int] = []
        self.cursors: list[FakeCursor] = []
        self.session: dict[str, Any] = {}
        self.rollbacks = 0
        self.closed = False
        self.fail_on: str | None = None
        self.error: Exception = psycopg2.Error("boom")

    def cursor(self, name: str | None = None) -> FakeCursor:
        cursor = FakeCursor(self, name)
        self.cursors.append(cursor)
        return cursor

    def set_session(self, **kwargs: Any) -> None:
        self.session = kwargs

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def connected(
    monkeypatch: pytest.MonkeyPatch, results: dict[str, Any] | None = None
) -> tuple[pg.PostgresConnector, FakeConn, list[dict[str, Any]]]:
    fake = FakeConn(results)
    calls: list[dict[str, Any]] = []

    def connect(**kwargs: Any) -> FakeConn:
        calls.append(kwargs)
        return fake

    monkeypatch.setattr(pg.psycopg2, "connect", connect)
    connector = pg.PostgresConnector()
    connector.connect(CFG)
    return connector, fake, calls


def test_config_defaults_and_validation() -> None:
    cfg = pg.PostgresConfig.model_validate(CFG)
    assert (cfg.port, cfg.sslmode, cfg.query_timeout) == (5432, "prefer", 300)
    for bad in (
        {**CFG, "host": ""},
        {**CFG, "port": 0},
        {**CFG, "sslmode": "maybe"},
        {**CFG, "extra": 1},
        {**CFG, "host": "a\nb"},
    ):
        with pytest.raises(ValidationError):
            pg.PostgresConfig.model_validate(bad)


def test_connect_passes_separate_arguments_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = {**CFG, "database": "erp sslmode=disable host=evil", "query_timeout": 60}
    fake = FakeConn()
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(pg.psycopg2, "connect", lambda **kw: calls.append(kw) or fake)
    pg.PostgresConnector().connect(hostile)
    kwargs = calls[0]
    assert (
        kwargs["dbname"] == "erp sslmode=disable host=evil"
        and kwargs["host"] == "db.example.com"
    )
    assert kwargs["sslmode"] == "prefer" and kwargs["application_name"] == "MagBI"
    assert (
        "default_transaction_read_only=on" in kwargs["options"]
        and "statement_timeout=60000" in kwargs["options"]
    )
    assert fake.session == {"readonly": True, "autocommit": False}


def test_invalid_config_error_does_not_leak_password() -> None:
    with pytest.raises(ConnectorError) as err:
        pg.PostgresConnector().connect({**CFG, "port": "x"})
    assert (
        err.value.code is ErrorCode.INVALID_CONFIG and "S3cret" not in err.value.message
    )


@pytest.mark.parametrize(
    ("pgcode", "message", "code"),
    [
        (
            "28P01",
            'FATAL:  password authentication failed for user "bi"',
            ErrorCode.AUTH_FAILED,
        ),
        ("3D000", 'FATAL:  database "nope" does not exist', ErrorCode.NOT_FOUND),
        (
            "57014",
            "ERROR:  canceling statement due to statement timeout",
            ErrorCode.TIMEOUT,
        ),
        ("42P01", 'ERROR:  relation "x" does not exist', ErrorCode.NOT_FOUND),
        ("42601", "ERROR:  syntax error at or near", ErrorCode.QUERY_FAILED),
    ],
)
def test_error_mapping(pgcode: str, message: str, code: ErrorCode) -> None:
    exc = psycopg2.Error(message)
    monkey = type("E", (psycopg2.Error,), {"pgcode": pgcode})(message)
    assert pg.map_error(monkey).code is code
    assert pg.map_error(exc).code in {
        code,
        ErrorCode.QUERY_FAILED,
        ErrorCode.UNREACHABLE,
    }


def test_unreachable_and_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(**_: Any) -> None:
        raise psycopg2.OperationalError(
            "could not connect to server: Connection refused (password=S3cret;pw)\n\tIs the server running?"
        )

    monkeypatch.setattr(pg.psycopg2, "connect", refuse)
    result = pg.PostgresConnector().test_connection(CFG)
    assert not result.success and result.code is ErrorCode.UNREACHABLE
    assert (
        result.error
        and "S3cret" not in result.error
        and "Is the server running" not in result.error
    )


def test_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    connector, fake, _ = connected(
        monkeypatch,
        {
            "SELECT version()": [
                ("PostgreSQL 16.2 on x86_64-pc-linux-gnu, compiled by gcc",)
            ],
            "FROM pg_namespace n\nJOIN pg_class": [("public",), ("sales",)],
            "c.relname, c.relkind, c.reltuples": [
                ("orders", "r", 120),
                ("open_orders", "v", -1),
            ],
            "pg_index i": [("orders", "id")],
            "FROM pg_attribute a": [
                ("orders", "id", "int4", "integer", False, "b", "N"),
                ("orders", "amount", "numeric", "numeric(12,2)", True, "b", "N"),
                ("orders", "tags", "_text", "text[]", True, "b", "A"),
                ("orders", "status", "order_status", "order_status", True, "e", "E"),
                (
                    "orders",
                    "placed",
                    "timestamptz",
                    "timestamp with time zone",
                    True,
                    "b",
                    "D",
                ),
                ("open_orders", "id", "int4", "integer", True, "b", "N"),
            ],
        },
    )
    assert connector.get_server_version() == "PostgreSQL 16.2 on x86_64-pc-linux-gnu"
    assert connector.list_schemas() == ["public", "sales"]
    orders, view = connector.list_tables("public")
    assert (orders.kind, orders.estimated_rows, view.kind, view.estimated_rows) == (
        "table",
        120,
        "view",
        None,
    )
    by_name = {c.name: c for c in orders.columns}
    assert by_name["id"].is_primary_key and not by_name["id"].is_nullable
    assert (
        by_name["amount"].data_type,
        by_name["amount"].precision,
        by_name["amount"].scale,
    ) == ("numeric", 12, 2)
    assert (
        by_name["tags"].data_type == "array"
        and by_name["status"].data_type == "user-defined"
    )
    plans = {p.column: p for p in plan_columns(orders.columns, connector.get_dialect())}
    assert (
        plans["amount"].duckdb_type == "DECIMAL(12,2)"
        and plans["placed"].cast == "utc_datetime"
    )
    assert (
        plans["tags"].cast == "string"
        and plans["status"].cast == "string"
        and plans["status"].warning is None
    )
    # Each catalog read ends its read-only transaction.
    assert fake.rollbacks >= 4


def test_describe_query(monkeypatch: pytest.MonkeyPatch) -> None:
    connector, fake, _ = connected(
        monkeypatch,
        {
            "AS magbi_query LIMIT 0": (
                [
                    Col("region", 25, None, -1, None, None, None),
                    Col("total", 1700, None, -1, 12, 2, None),
                ],
                [],
            ),
            "FROM pg_type WHERE oid": [
                (25, "text", "b", "S"),
                (1700, "numeric", "b", "N"),
            ],
        },
    )
    columns = connector.describe_query(
        "SELECT region, sum(amount) AS total FROM orders GROUP BY region;"
    )
    assert [(c.name, c.data_type, c.precision, c.scale) for c in columns] == [
        ("region", "text", None, None),
        ("total", "numeric", 12, 2),
    ]
    assert (
        "FROM (SELECT region, sum(amount) AS total FROM orders GROUP BY region) AS magbi_query LIMIT 0"
        in fake.executed[0][0]
    )
    with pytest.raises(ConnectorError):
        connector.describe_query("DELETE FROM orders")


def test_execute_query_streams_with_a_server_side_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [(i,) for i in range(5)]
    connector, fake, _ = connected(monkeypatch, {'FROM "public"."orders"': rows})
    assert (
        list(
            connector.execute_query('SELECT "id" FROM "public"."orders"', batch_size=2)
        )
        == rows
    )
    stream = [c for c in fake.cursors if c.name]
    assert (
        stream
        and stream[0].name == "magbi_stream"
        and stream[0].itersize == 2
        and stream[0].closed
    )
    assert fake.fetches == [2, 2, 1, 0]


def test_execute_query_is_lazy_and_closes_on_early_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector, fake, _ = connected(monkeypatch, {'FROM "t"': [(1,), (2,), (3,)]})
    rows = connector.execute_query('SELECT "a" FROM "t"', batch_size=1)
    assert not fake.executed
    assert next(rows) == (1,)
    rows.close()  # type: ignore[attr-defined]
    assert next(c for c in fake.cursors if c.name).closed


def test_non_select_and_two_statements_refused_before_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector, fake, _ = connected(monkeypatch)
    for sql in ("DROP TABLE x", "SELECT 1; DELETE FROM x", "UPDATE x SET a = 1"):
        with pytest.raises(ConnectorError):
            list(connector.execute_query(sql))
    assert not fake.executed


def test_midstream_error_is_mapped_and_scrubbed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector, fake, _ = connected(monkeypatch)
    fake.fail_on = "FROM"
    fake.error = type("E", (psycopg2.Error,), {"pgcode": "57014"})(
        "ERROR:  canceling statement due to statement timeout"
    )
    with pytest.raises(ConnectorError) as err:
        list(connector.execute_query('SELECT "a" FROM "t"'))
    assert err.value.code is ErrorCode.TIMEOUT


TABLE = SourceTable(
    "public",
    "Orders",
    [
        SourceColumn("id", "integer"),
        SourceColumn("placed", "timestamptz"),
        SourceColumn("tags", "_text"),
    ],
)


def test_build_select_quotes_and_casts() -> None:
    assert (
        pg.build_select_sql(TABLE)
        == 'SELECT "id", "placed", "tags" FROM "public"."Orders"'
    )
    sql = pg.build_select_sql(
        TABLE, {"placed": "utc_datetime", "tags": "string"}, limit=5
    )
    assert (
        sql
        == 'SELECT "id", "placed" AT TIME ZONE \'UTC\' AS "placed", CAST("tags" AS TEXT) AS "tags" FROM "public"."Orders" LIMIT 5'
    )
    assert check_read_only(sql)


def test_hostile_identifiers_are_escaped() -> None:
    table = SourceTable('we"ird', 'x"; DROP TABLE y; --', [SourceColumn('a"b', "text")])
    sql = pg.build_select_sql(table)
    assert sql == 'SELECT "a""b" FROM "we""ird"."x""; DROP TABLE y; --"'


def test_count_and_catalog_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    connector, fake, _ = connected(
        monkeypatch,
        {
            "c.relname, c.relkind": [("orders", "r", 3)],
            "FROM pg_attribute a": [
                ("orders", "id", "int4", "integer", False, "b", "N")
            ],
            "COUNT(*)": [(3,)],
        },
    )
    assert connector.get_row_count("public", "orders") == 3
    assert any(
        'SELECT COUNT(*) FROM "public"."orders"' in sql for sql, _, _ in fake.executed
    )
    with pytest.raises(ConnectorError) as err:
        connector.get_row_count("public", "missing")
    assert err.value.code is ErrorCode.NOT_FOUND


def test_requires_connection_and_close_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ConnectorError) as err:
        pg.PostgresConnector().list_schemas()
    assert err.value.code is ErrorCode.NOT_CONNECTED
    connector, fake, _ = connected(monkeypatch)
    connector.close()
    connector.close()
    assert fake.closed and connector.get_dialect() == "postgres"
