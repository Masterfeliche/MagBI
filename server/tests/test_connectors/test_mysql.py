"""MySQL connector against a fake PyMySQL connection (no server needed)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Self

import pymysql
import pytest
from pydantic import ValidationError
from pymysql.constants import FIELD_TYPE

from magbi.connectors import mysql as my
from magbi.connectors.base import SourceColumn, SourceTable
from magbi.connectors.errors import ConnectorError, ErrorCode
from magbi.connectors.types import coercer_for, plan_columns

CFG: dict[str, Any] = {
    "host": "db.example.com",
    "database": "shop",
    "username": "bi",
    "password": "S3cret;pw",
}


class FakeCursor:
    def __init__(self, conn: FakeConn, kind: Any = None) -> None:
        self.conn, self.kind = conn, kind
        self.rows: list[tuple[Any, ...]] = []
        self.description: list[tuple[Any, ...]] | None = None
        self.closed = False

    def execute(self, sql: str, params: Any = None) -> None:
        self.conn.executed.append(sql)
        for fail, error in self.conn.failures.items():
            if fail in sql:
                raise error
        for key, result in self.conn.results.items():
            if key in sql:
                if isinstance(result, dict):
                    self.description, self.rows = result["description"], []
                else:
                    self.rows = list(result)
                return
        self.rows = []

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows, self.rows = self.rows, []
        return rows

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        batch, self.rows = self.rows[:size], self.rows[size:]
        return batch

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class FakeConn:
    def __init__(
        self,
        results: dict[str, Any] | None = None,
        failures: dict[str, Exception] | None = None,
    ) -> None:
        self.results = results or {}
        self.failures = failures or {}
        self.executed: list[str] = []
        self.cursors: list[FakeCursor] = []
        self.closed = False

    def cursor(self, kind: Any = None) -> FakeCursor:
        cursor = FakeCursor(self, kind)
        self.cursors.append(cursor)
        return cursor

    def close(self) -> None:
        self.closed = True


def connected(
    monkeypatch: pytest.MonkeyPatch,
    results: dict[str, Any] | None = None,
    failures: dict[str, Exception] | None = None,
) -> tuple[my.MySqlConnector, FakeConn, list[dict[str, Any]]]:
    fake = FakeConn(results, failures)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(my.pymysql, "connect", lambda **kw: calls.append(kw) or fake)
    connector = my.MySqlConnector()
    connector.connect(CFG)
    return connector, fake, calls


def test_config_and_connect_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = my.MySqlConfig.model_validate({**CFG, "database": None})
    assert (cfg.port, cfg.ssl, cfg.database) == (3306, False, None)
    for bad in ({**CFG, "username": ""}, {**CFG, "port": 70000}, {**CFG, "bogus": 1}):
        with pytest.raises(ValidationError):
            my.MySqlConfig.model_validate(bad)
    _, fake, calls = connected(monkeypatch)
    kwargs = calls[0]
    assert (
        kwargs["charset"] == "utf8mb4"
        and kwargs["autocommit"]
        and kwargs["database"] == "shop"
    )
    assert fake.executed[:2] == [
        "SET SESSION TRANSACTION READ ONLY",
        "SET SESSION time_zone = '+00:00'",
    ]


def test_unknown_time_limit_setting_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    # MySQL lacks MariaDB's max_statement_time (and the other way round): still connected.
    connector, fake, _ = connected(
        monkeypatch,
        failures={
            "max_statement_time": pymysql.err.OperationalError(
                1193, "Unknown system variable"
            )
        },
    )
    assert connector._conn is fake


def test_read_only_session_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeConn(
        failures={"READ ONLY": pymysql.err.OperationalError(1064, "syntax")}
    )
    monkeypatch.setattr(my.pymysql, "connect", lambda **kw: fake)
    with pytest.raises(ConnectorError):
        my.MySqlConnector().connect(CFG)
    assert fake.closed


@pytest.mark.parametrize(
    ("args", "code"),
    [
        (
            (1045, "Access denied for user 'bi'@'10.0.0.1' (using password: YES)"),
            ErrorCode.AUTH_FAILED,
        ),
        ((1049, "Unknown database 'nope'"), ErrorCode.NOT_FOUND),
        ((1146, "Table 'shop.x' doesn't exist"), ErrorCode.NOT_FOUND),
        (
            (
                3024,
                "Query execution was interrupted, maximum statement execution time exceeded",
            ),
            ErrorCode.TIMEOUT,
        ),
        (
            (
                2003,
                "Can't connect to MySQL server on 'db' ([Errno 111] Connection refused)",
            ),
            ErrorCode.UNREACHABLE,
        ),
        ((1064, "You have an error in your SQL syntax"), ErrorCode.QUERY_FAILED),
    ],
)
def test_error_mapping(args: tuple[int, str], code: ErrorCode) -> None:
    assert my.map_error(pymysql.err.OperationalError(*args)).code is code


def test_failed_connect_is_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(**_: Any) -> None:
        raise pymysql.err.OperationalError(1045, "Access denied (password S3cret;pw)")

    monkeypatch.setattr(my.pymysql, "connect", refuse)
    result = my.MySqlConnector().test_connection(CFG)
    assert (
        not result.success
        and result.code is ErrorCode.AUTH_FAILED
        and "S3cret" not in (result.error or "")
    )


def test_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    connector, _, _ = connected(
        monkeypatch,
        {
            "SELECT VERSION()": [("10.11.6-MariaDB-0+deb12u1",)],
            "information_schema.SCHEMATA": [("shop",)],
            "information_schema.TABLES": [
                ("orders", "BASE TABLE", 42),
                ("v_open", "VIEW", None),
            ],
            "information_schema.COLUMNS": [
                (
                    "orders",
                    "id",
                    "bigint",
                    "bigint(20) unsigned",
                    "NO",
                    "PRI",
                    None,
                    20,
                    0,
                ),
                ("orders", "total", "decimal", "decimal(12,2)", "YES", "", None, 12, 2),
                (
                    "orders",
                    "placed",
                    "datetime",
                    "datetime",
                    "YES",
                    "",
                    None,
                    None,
                    None,
                ),
                (
                    "orders",
                    "note",
                    "longtext",
                    "longtext",
                    "YES",
                    "",
                    4294967295,
                    None,
                    None,
                ),
                ("v_open", "id", "int", "int(11)", "YES", "", None, 10, 0),
            ],
        },
    )
    assert connector.get_server_version() == "MariaDB 10.11.6"
    assert connector.list_schemas() == ["shop"]
    orders, view = connector.list_tables("shop")
    assert (orders.estimated_rows, view.kind) == (42, "view")
    by_name = {c.name: c for c in orders.columns}
    assert by_name["id"].data_type == "bigint unsigned" and by_name["id"].is_primary_key
    assert by_name["note"].max_length is None
    plans = {p.column: p for p in plan_columns(orders.columns, connector.get_dialect())}
    assert (
        plans["id"].duckdb_type == "DECIMAL(20,0)"
        and plans["total"].duckdb_type == "DECIMAL(12,2)"
    )
    assert plans["placed"].coerce == "datetime"


def test_describe_query(monkeypatch: pytest.MonkeyPatch) -> None:
    connector, fake, _ = connected(
        monkeypatch,
        {
            "AS magbi_query LIMIT 0": {
                "description": [
                    ("region", FIELD_TYPE.VAR_STRING, None, 80, 0, 0, True),
                    ("total", FIELD_TYPE.NEWDECIMAL, None, 14, 12, 2, True),
                    ("note", FIELD_TYPE.BLOB, None, 0, 0, 0, True),
                ]
            }
        },
    )
    columns = connector.describe_query(
        "SELECT region, SUM(total) AS total, note FROM orders GROUP BY region"
    )
    assert [(c.name, c.data_type, c.precision, c.scale) for c in columns] == [
        ("region", "varchar", None, None),
        ("total", "decimal", 12, 2),
        ("note", "text", None, None),
    ]
    assert any("FROM (SELECT region" in sql for sql in fake.executed)


def test_execute_query_streams_unbuffered(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [(i,) for i in range(5)]
    connector, fake, _ = connected(monkeypatch, {"FROM `shop`.`orders`": rows})
    assert (
        list(connector.execute_query("SELECT `id` FROM `shop`.`orders`", batch_size=2))
        == rows
    )
    stream = fake.cursors[-1]
    assert stream.kind is pymysql.cursors.SSCursor and stream.closed


def test_writes_refused_before_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    connector, fake, _ = connected(monkeypatch)
    before = len(fake.executed)
    for sql in (
        "DELETE FROM x",
        "SELECT 1; DROP TABLE x",
        "SELECT * INTO OUTFILE '/tmp/x' FROM y",
    ):
        with pytest.raises(ConnectorError):
            list(connector.execute_query(sql))
    assert len(fake.executed) == before


def test_build_select_quotes_with_backticks_and_casts_to_text() -> None:
    table = SourceTable(
        "shop", "Order`s", [SourceColumn("id", "int"), SourceColumn("t", "time")]
    )
    assert my.build_select_sql(table) == "SELECT `id`, `t` FROM `shop`.`Order``s`"
    assert (
        my.build_select_sql(table, {"t": "string"}, 3)
        == "SELECT `id`, CAST(`t` AS CHAR) AS `t` FROM `shop`.`Order``s` LIMIT 3"
    )


def test_zero_dates_become_blank_and_values_convert() -> None:
    date_plan, stamp_plan = plan_columns(
        [SourceColumn("d", "date"), SourceColumn("s", "datetime")], "mysql"
    )
    to_date, to_stamp = coercer_for(date_plan), coercer_for(stamp_plan)
    assert to_date is not None and to_stamp is not None
    assert to_date("0000-00-00") is None and to_date(dt.date(2026, 10, 31)) == dt.date(
        2026, 10, 31
    )
    assert to_stamp("0000-00-00 00:00:00") is None and to_stamp(
        dt.datetime(2026, 1, 2, 3, 4)
    ) == dt.datetime(2026, 1, 2, 3, 4)
    assert (
        plan_columns([SourceColumn("b", "bigint unsigned")], "mysql")[
            0
        ].arrow_type.precision
        == 20
    )
    assert Decimal(18446744073709551615).as_tuple()  # fits DECIMAL(20,0)


def test_dialect_and_close(monkeypatch: pytest.MonkeyPatch) -> None:
    connector, fake, _ = connected(monkeypatch)
    assert connector.get_dialect() == "mysql"
    connector.close()
    connector.close()
    assert fake.closed
    with pytest.raises(ConnectorError) as err:
        connector.list_schemas()
    assert err.value.code is ErrorCode.NOT_CONNECTED
