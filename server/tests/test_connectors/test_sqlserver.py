"""Unit tests for the SQL Server connector using a scripted fake pyodbc."""

from __future__ import annotations

from typing import Any

import pyodbc
import pytest

from magbi.connectors import sqlserver
from magbi.connectors.base import SourceColumn, SourceTable
from magbi.connectors.errors import ConnectorError, ErrorCode
from magbi.connectors.sqlserver import (
    SqlServerConfig,
    SqlServerConnector,
    build_connection_string,
    build_count_sql,
    build_select_sql,
    map_error,
    odbc_value,
    scrub_message,
)

PASSWORD = "p@ss};Server=evil;PWD={x"
BASE = {
    "host": "db.local",
    "database": "MSD_ERP",
    "username": "bi",
    "password": PASSWORD,
}


def odbc_error(state: str, message: str) -> pyodbc.Error:
    return pyodbc.Error(
        state, f"[{state}] [Microsoft][ODBC Driver 18 for SQL Server]{message}"
    )


# -- fakes --------------------------------------------------------------------


class FakeCursor:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn
        self.rows: list[tuple[Any, ...]] = []
        self.pos = 0
        self.closed = False
        self.fetch_sizes: list[int] = []

    def execute(self, sql: str, *params: Any) -> None:
        self.conn.executed.append((sql, params))
        for needle, result in self.conn.script:
            if needle in sql:
                if isinstance(result, Exception):
                    raise result
                self.rows = list(result)
                return
        raise AssertionError(f"unscripted SQL: {sql[:80]}")

    def fetchall(self) -> list[tuple[Any, ...]]:
        out, self.pos = self.rows[self.pos :], len(self.rows)
        return out

    def fetchmany(self, n: int) -> list[tuple[Any, ...]]:
        self.fetch_sizes.append(n)
        out = self.rows[self.pos : self.pos + n]
        self.pos += n
        return out

    def close(self) -> None:
        self.closed = True


class FakeConn:
    def __init__(self, script: list[tuple[str, Any]] | None = None) -> None:
        self.script = script or []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.cursors: list[FakeCursor] = []
        self.timeout = -1
        self.closed = False
        self.close_error: Exception | None = None

    def cursor(self) -> FakeCursor:
        c = FakeCursor(self)
        self.cursors.append(c)
        return c

    def close(self) -> None:
        self.closed = True
        if self.close_error:
            raise self.close_error


@pytest.fixture
def connect_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    conn = FakeConn()
    monkeypatch.setattr(
        sqlserver.pyodbc,
        "connect",
        lambda cs, **kw: (calls.append((cs, kw)), conn)[1],
    )
    calls.append(("__conn__", {"conn": conn}))
    return calls


def connected(
    monkeypatch: pytest.MonkeyPatch, script: list[tuple[str, Any]]
) -> tuple[SqlServerConnector, FakeConn]:
    conn = FakeConn(script)
    monkeypatch.setattr(sqlserver.pyodbc, "connect", lambda cs, **kw: conn)
    c = SqlServerConnector()
    c.connect(BASE)
    return c, conn


# -- config / connection string -------------------------------------------------


def test_config_defaults() -> None:
    cfg = SqlServerConfig.model_validate(BASE)
    assert cfg.encrypt is True and cfg.trust_server_certificate is False
    assert cfg.driver == "ODBC Driver 18 for SQL Server"
    assert cfg.server == "db.local,1433"


@pytest.mark.parametrize(
    ("host", "port", "server"),
    [
        ("db.local", 1434, "db.local,1434"),
        ("192.168.1.3\\SQLSERVER2025", None, "192.168.1.3\\SQLSERVER2025"),
        ("192.168.1.3\\SQLSERVER2025", 1500, "192.168.1.3\\SQLSERVER2025,1500"),
    ],
)
def test_server_string(host: str, port: int | None, server: str) -> None:
    assert (
        SqlServerConfig.model_validate({**BASE, "host": host, "port": port}).server
        == server
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"username": None},
        {"password": None},
        {"host": ""},
        {"host": "a\nb"},
        {"database": "x\x00y"},
        {"port": 0},
        {"port": 70000},
        {"connection_timeout": 0},
        {"unknown_field": 1},
    ],
)
def test_invalid_config_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        SqlServerConfig.model_validate({**BASE, **bad})


def test_integrated_auth_needs_no_credentials() -> None:
    cfg = SqlServerConfig.model_validate(
        {"host": "h", "database": "d", "authentication": "integrated"}
    )
    cs = build_connection_string(cfg)
    assert "Trusted_Connection=yes" in cs and "UID=" not in cs and "PWD=" not in cs


def test_odbc_value_escapes_closing_brace() -> None:
    assert odbc_value("a}b") == "{a}}b}"
    assert odbc_value("plain") == "{plain}"


def parse_odbc(cs: str) -> dict[str, str]:
    """Parse a connection string the way an ODBC driver does (braces, doubled ``}``)."""
    out: dict[str, str] = {}
    i = 0
    while i < len(cs):
        eq = cs.index("=", i)
        key = cs[i:eq]
        i = eq + 1
        if i < len(cs) and cs[i] == "{":
            i += 1
            value = ""
            while True:
                if cs[i] == "}":
                    if i + 1 < len(cs) and cs[i + 1] == "}":
                        value += "}"
                        i += 2
                        continue
                    i += 1
                    break
                value += cs[i]
                i += 1
        else:
            end = cs.find(";", i)
            end = len(cs) if end == -1 else end
            value, i = cs[i:end], end
        out[key] = value
        if i < len(cs):
            assert cs[i] == ";", f"expected ';' at {i}"
            i += 1
    return out


def test_connection_string_round_trips_hostile_values() -> None:
    hostile = {**BASE, "host": "h};Server={evil", "database": "d};UID={root"}
    parsed = parse_odbc(
        build_connection_string(SqlServerConfig.model_validate(hostile))
    )
    assert parsed["PWD"] == PASSWORD  # password survives intact, injects nothing
    assert parsed["SERVER"] == "h};Server={evil,1433"
    assert parsed["DATABASE"] == "d};UID={root"
    assert parsed["UID"] == "bi"
    assert "evil" not in parsed and "Server" not in parsed
    assert list(parsed) == [
        "DRIVER",
        "SERVER",
        "DATABASE",
        "Encrypt",
        "TrustServerCertificate",
        "ApplicationIntent",
        "APP",
        "UID",
        "PWD",
    ]


def test_connection_string_security_defaults() -> None:
    parsed = parse_odbc(build_connection_string(SqlServerConfig.model_validate(BASE)))
    assert parsed["Encrypt"] == "yes"
    assert parsed["TrustServerCertificate"] == "no"
    assert parsed["ApplicationIntent"] == "ReadOnly"


def test_connect_passes_timeout_and_autocommit(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        sqlserver.pyodbc, "connect", lambda cs, **kw: (seen.update(kw), FakeConn())[1]
    )
    SqlServerConnector().connect({**BASE, "connection_timeout": 7})
    assert seen == {"timeout": 7, "autocommit": True}


def test_invalid_config_error_does_not_leak_password() -> None:
    with pytest.raises(ConnectorError) as exc:
        SqlServerConnector().connect({**BASE, "port": 0})
    assert exc.value.code is ErrorCode.INVALID_CONFIG
    assert PASSWORD not in exc.value.message
    assert "port" in exc.value.message


# -- error mapping ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "message", "code"),
    [
        (
            "28000",
            "[SQL Server]Login failed for user 'bi'. (18456) (SQLDriverConnect)",
            ErrorCode.AUTH_FAILED,
        ),
        (
            "42000",
            '[SQL Server]Cannot open database "X" requested by the login. (4060)',
            ErrorCode.NOT_FOUND,
        ),
        ("HYT00", "Login timeout expired (0) (SQLDriverConnect)", ErrorCode.TIMEOUT),
        (
            "08001",
            "TCP Provider: No such host is known. (11001)",
            ErrorCode.UNREACHABLE,
        ),
        ("08S01", "Communication link failure (0)", ErrorCode.UNREACHABLE),
        (
            "IM002",
            "Data source name not found and no default driver specified (0)",
            ErrorCode.INVALID_CONFIG,
        ),
        (
            "42S02",
            "[SQL Server]Invalid object name 'dbo.X'. (208)",
            ErrorCode.NOT_FOUND,
        ),
        (
            "42000",
            "[SQL Server]Incorrect syntax near 'x'. (102)",
            ErrorCode.QUERY_FAILED,
        ),
    ],
)
def test_error_mapping(state: str, message: str, code: ErrorCode) -> None:
    assert map_error(pyodbc.Error(state, message)).code is code


def test_scrub_removes_driver_noise() -> None:
    msg = "[28000] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]Login failed for user 'bi'. (18456) (SQLDriverConnect)"
    assert scrub_message(msg) == "Login failed for user 'bi'."


def test_scrub_redacts_secrets_and_pwd_keyword() -> None:
    assert "hunter2" not in scrub_message("bad password hunter2 here", ("hunter2",))
    assert scrub_message("DRIVER=x;PWD={a}};b};UID=u") == "DRIVER=x;PWD=***;UID=u"
    assert "secret" not in scrub_message("PWD=secret;DATABASE=d")


def test_connect_failure_is_mapped_and_scrubbed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(cs: str, **kw: Any) -> None:
        raise odbc_error(
            "28000", f"[SQL Server]Login failed for user 'bi' pw={PASSWORD} (18456)"
        )

    monkeypatch.setattr(sqlserver.pyodbc, "connect", boom)
    with pytest.raises(ConnectorError) as exc:
        SqlServerConnector().connect(BASE)
    assert exc.value.code is ErrorCode.AUTH_FAILED
    assert PASSWORD not in exc.value.message
    assert exc.value.__cause__ is None  # original (unscrubbed) error is not chained


def test_test_connection_reports_failure_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(cs: str, **kw: Any) -> None:
        raise odbc_error("HYT00", "Login timeout expired (0)")

    monkeypatch.setattr(sqlserver.pyodbc, "connect", boom)
    res = SqlServerConnector().test_connection(BASE)
    assert res.success is False and res.code is ErrorCode.TIMEOUT


# -- metadata -----------------------------------------------------------------------

CATALOG: list[tuple[str, Any]] = [
    ("@@VERSION", [("Microsoft SQL Server 2022 (RTM) - 16.0.1000\n\tCopyright",)]),
    ("SELECT DISTINCT s.name", [("dbo",), ("vetsp",)]),
    ("SELECT o.object_id, o.name, o.type", [(10, "Trip", "U "), (11, "vTrip", "V ")]),
    (
        "COALESCE(base.name",
        [
            (10, "TripId", "uniqueidentifier", 16, 0, 0, 0),
            (10, "Name", "nvarchar", 100, 0, 0, 1),
            (10, "Big", "nvarchar", -1, 0, 0, 1),
            (10, "Distance", "decimal", 9, 18, 2, 1),
            (11, "TripId", "uniqueidentifier", 16, 0, 0, 0),
        ],
    ),
    ("i.is_primary_key", [(10, 1, "TripId")]),
    ("dm_db_partition_stats", [(10, 1234)]),
]


def test_server_version_first_line_only(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = connected(monkeypatch, CATALOG)
    assert c.get_server_version() == "Microsoft SQL Server 2022 (RTM) - 16.0.1000"


def test_list_schemas(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = connected(monkeypatch, CATALOG)
    assert c.list_schemas() == ["dbo", "vetsp"]


def test_test_connection_success(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn(CATALOG)
    monkeypatch.setattr(sqlserver.pyodbc, "connect", lambda cs, **kw: conn)
    res = SqlServerConnector().test_connection(BASE)
    assert res.success and res.schemas == ["dbo", "vetsp"]
    assert res.server_version and res.server_version.startswith(
        "Microsoft SQL Server 2022"
    )
    assert conn.closed


def test_list_tables_assembles_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    c, conn = connected(monkeypatch, CATALOG)
    trip, view = c.list_tables("dbo")
    assert (trip.name, trip.kind, trip.estimated_rows) == ("Trip", "table", 1234)
    assert (view.name, view.kind, view.estimated_rows) == ("vTrip", "view", None)
    by_name = {col.name: col for col in trip.columns}
    assert by_name["TripId"].is_primary_key and not by_name["TripId"].is_nullable
    assert by_name["Name"].max_length == 50  # 100 bytes of nvarchar = 50 chars
    assert by_name["Big"].max_length == -1  # MAX stays -1
    assert (by_name["Distance"].precision, by_name["Distance"].scale) == (18, 2)
    assert by_name["Name"].precision is None
    assert all(params == ("dbo",) for _, params in conn.executed[1:])  # schema is bound


def test_list_tables_survives_missing_estimate_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = [
        (
            n,
            odbc_error(
                "42000", "[SQL Server]VIEW DATABASE STATE permission denied. (300)"
            ),
        )
        if n == "dm_db_partition_stats"
        else (n, r)
        for n, r in CATALOG
    ]
    c, _ = connected(monkeypatch, script)
    assert c.list_tables("dbo")[0].estimated_rows is None


def test_list_tables_empty_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    script = [(n, [] if "o.object_id, o.name" in n else r) for n, r in CATALOG]
    c, _ = connected(monkeypatch, script)
    assert c.list_tables("nothing") == []


def test_metadata_error_is_mapped(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = connected(
        monkeypatch,
        [("SELECT DISTINCT s.name", odbc_error("42000", "[SQL Server]boom (1)"))],
    )
    with pytest.raises(ConnectorError) as exc:
        c.list_schemas()
    assert exc.value.code is ErrorCode.QUERY_FAILED


# -- queries -------------------------------------------------------------------------


def test_execute_query_streams_in_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [(i, f"n{i}") for i in range(25)]
    c, conn = connected(monkeypatch, [("SELECT", rows)])
    out = list(c.execute_query("SELECT a, b FROM t", batch_size=10))
    assert out == rows
    cursor = conn.cursors[-1]
    assert cursor.fetch_sizes == [10, 10, 10, 10]  # 10 + 10 + 5, then the empty fetch
    assert cursor.closed


def test_execute_query_is_lazy_and_closes_on_early_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, conn = connected(monkeypatch, [("SELECT", [(i,) for i in range(100)])])
    stream = c.execute_query("SELECT a FROM t", batch_size=10)
    assert next(stream) == (0,)
    cursor = conn.cursors[-1]
    assert cursor.pos == 10 and not cursor.closed  # only one batch fetched so far
    stream.close()  # type: ignore[attr-defined]
    assert cursor.closed


def test_execute_query_sets_query_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn([("SELECT", [])])
    monkeypatch.setattr(sqlserver.pyodbc, "connect", lambda cs, **kw: conn)
    c = SqlServerConnector()
    c.connect({**BASE, "query_timeout": 42})
    list(c.execute_query("SELECT 1"))
    assert conn.timeout == 42


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE x",
        "UPDATE t SET a = 1",
        "DELETE FROM t",
        "EXEC sp_who",
        "SELECT 1; DROP TABLE x",
        "SELECT 1; SELECT 2",
        "INSERT INTO t VALUES (1)",
        "",
    ],
)
def test_non_select_rejected_before_reaching_server(
    monkeypatch: pytest.MonkeyPatch, sql: str
) -> None:
    c, conn = connected(monkeypatch, [])
    with pytest.raises(ConnectorError) as exc:
        c.execute_query(sql)
    assert exc.value.code is ErrorCode.UNSUPPORTED
    assert conn.executed == []


def test_cte_select_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = connected(monkeypatch, [("WITH", [(1,)])])
    assert list(c.execute_query("WITH x AS (SELECT 1 AS a) SELECT a FROM x")) == [(1,)]


def test_midstream_error_is_mapped_and_cursor_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Exploding(FakeCursor):
        def fetchmany(self, n: int) -> list[tuple[Any, ...]]:
            if self.pos:
                raise odbc_error("08S01", "Communication link failure (0)")
            return super().fetchmany(n)

    c, conn = connected(monkeypatch, [("SELECT", [(1,), (2,)])])
    conn.cursor = lambda: (cur := Exploding(conn), conn.cursors.append(cur), cur)[2]  # type: ignore[method-assign]
    stream = c.execute_query("SELECT a FROM t", batch_size=2)
    assert [next(stream), next(stream)] == [(1,), (2,)]
    with pytest.raises(ConnectorError) as exc:
        next(stream)
    assert exc.value.code is ErrorCode.UNREACHABLE
    assert conn.cursors[-1].closed


def test_row_count_checks_catalog_first(monkeypatch: pytest.MonkeyPatch) -> None:
    c, conn = connected(monkeypatch, [*CATALOG, ("COUNT_BIG", [(99,)])])
    assert c.get_row_count("dbo", "Trip") == 99
    assert any("COUNT_BIG" in sql and "[dbo].[Trip]" in sql for sql, _ in conn.executed)

    with pytest.raises(ConnectorError) as exc:
        c.get_row_count("dbo", "Trip]; DROP TABLE x;--")
    assert exc.value.code is ErrorCode.NOT_FOUND
    assert sum("COUNT_BIG" in sql for sql, _ in conn.executed) == 1


def test_preview_goes_through_catalog_and_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, conn = connected(monkeypatch, [*CATALOG, ("TOP 5", [(1,)])])
    assert list(c.preview("dbo", "Trip", limit=5)) == [(1,)]
    assert "SELECT TOP 5" in conn.executed[-1][0]


# -- sql builders ----------------------------------------------------------------------

TABLE = SourceTable(
    "dbo",
    "Trip",
    [SourceColumn("TripId", "uniqueidentifier"), SourceColumn("Geo", "geography")],
)


def test_build_select_quotes_everything() -> None:
    assert build_select_sql(TABLE) == "SELECT [TripId], [Geo] FROM [dbo].[Trip]"


def test_build_select_limit_and_casts() -> None:
    sql = build_select_sql(TABLE, {"Geo": "string"}, limit=10)
    assert sql == (
        "SELECT TOP 10 [TripId], CAST([Geo] AS NVARCHAR(MAX)) AS [Geo] FROM [dbo].[Trip]"
    )


def test_build_select_utc_cast() -> None:
    t = SourceTable("dbo", "E", [SourceColumn("At", "datetimeoffset")])
    assert "CAST(SWITCHOFFSET([At], 0) AS DATETIME2(6)) AS [At]" in build_select_sql(
        t, {"At": "utc_datetime"}
    )


def test_hostile_identifiers_are_escaped() -> None:
    t = SourceTable("s]x", 'T]";--', [SourceColumn("c]1", "int")])
    sql = build_select_sql(t)
    assert sql == 'SELECT [c]]1] FROM [s]]x].[T]]";--]'
    assert build_count_sql(t) == 'SELECT COUNT_BIG(*) FROM [s]]x].[T]]";--]'


def test_build_select_rejects_empty_and_negative() -> None:
    with pytest.raises(ConnectorError):
        build_select_sql(SourceTable("dbo", "Empty", []))
    with pytest.raises(ValueError):
        build_select_sql(TABLE, limit=-1)


def test_built_selects_pass_the_select_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = connected(monkeypatch, [("SELECT", [])])
    t = SourceTable(
        "s]x", 'T]";--', [SourceColumn("c]1", "int"), SourceColumn("d", "xml")]
    )
    list(c.execute_query(c.build_select(t, casts={"d": "string"}, limit=3)))


# -- lifecycle --------------------------------------------------------------------------


def test_requires_connection() -> None:
    c = SqlServerConnector()
    for call in (c.list_schemas, c.get_server_version, lambda: c.list_tables("dbo")):
        with pytest.raises(ConnectorError) as exc:
            call()
        assert exc.value.code is ErrorCode.NOT_CONNECTED
    with pytest.raises(ConnectorError):
        c.execute_query("SELECT 1")


def test_close_is_idempotent_and_swallows_driver_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, conn = connected(monkeypatch, [])
    conn.close_error = pyodbc.Error("08S01", "already gone")
    c.close()
    c.close()
    assert conn.closed


def test_reconnect_closes_previous_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    conns = [FakeConn(), FakeConn()]
    it = iter(conns)
    monkeypatch.setattr(sqlserver.pyodbc, "connect", lambda cs, **kw: next(it))
    c = SqlServerConnector()
    c.connect(BASE)
    c.connect(BASE)
    assert conns[0].closed and not conns[1].closed


def test_dialect() -> None:
    assert SqlServerConnector().get_dialect() == "tsql"
