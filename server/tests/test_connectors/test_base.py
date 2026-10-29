import pytest

from magbi.connectors.base import (
    ConnectionTestResult,
    Connector,
    SourceColumn,
    SourceTable,
)
from magbi.connectors.errors import ConnectorError, ErrorCode
from tests.fakes import FakeConnector

TABLE = SourceTable(
    schema="dbo",
    name="Trip",
    columns=[
        SourceColumn("TripId", "uniqueidentifier", False, True),
        SourceColumn("Distance", "decimal", True, precision=18, scale=2),
    ],
    estimated_rows=3,
)


def make(**kw: object) -> FakeConnector:
    return FakeConnector(
        [TABLE],
        {"dbo.Trip": [("a", 1), ("b", 2), ("c", 3)]},
        **kw,  # type: ignore[arg-type]
    )


def test_connector_is_abstract() -> None:
    with pytest.raises(TypeError):
        Connector()  # type: ignore[abstract]


def test_source_objects_are_immutable_values() -> None:
    assert TABLE.qualified_name == "dbo.Trip"
    assert TABLE.kind == "table"
    with pytest.raises(AttributeError):
        TABLE.name = "x"  # type: ignore[misc]
    assert SourceColumn("a", "int") == SourceColumn("a", "int")


def test_connector_error_has_code_and_message() -> None:
    err = ConnectorError(ErrorCode.AUTH_FAILED, "Login failed")
    assert err.code is ErrorCode.AUTH_FAILED
    assert str(err) == "AUTH_FAILED: Login failed"


def test_test_connection_success_closes() -> None:
    c = make()
    res = c.test_connection({"host": "x"})
    assert res == ConnectionTestResult(
        success=True,
        server_version="FakeDB 1.0",
        schemas=["dbo"],
        latency_ms=res.latency_ms,
    )
    assert res.latency_ms is not None and res.latency_ms >= 0
    assert c.close_calls == 1 and not c.connected


def test_test_connection_failure_returns_result_and_closes() -> None:
    c = make(
        fail_connect=ConnectorError(ErrorCode.AUTH_FAILED, "Login failed for user")
    )
    res = c.test_connection({})
    assert res.success is False
    assert res.code is ErrorCode.AUTH_FAILED
    assert res.error == "Login failed for user"
    assert c.close_calls == 1


def test_find_table_and_not_found() -> None:
    c = make()
    c.connect({})
    assert c.find_table("dbo", "Trip") is TABLE
    with pytest.raises(ConnectorError) as exc:
        c.find_table("dbo", "Nope")
    assert exc.value.code is ErrorCode.NOT_FOUND


def test_preview_limits_rows() -> None:
    c = make()
    c.connect({})
    assert list(c.preview("dbo", "Trip", limit=2)) == [("a", 1), ("b", 2)]


def test_preview_unknown_table_never_runs_sql() -> None:
    c = make()
    c.connect({})
    with pytest.raises(ConnectorError):
        c.preview("dbo", "Trip; DROP TABLE x")
    assert c.queries == []


def test_context_manager_closes() -> None:
    with make() as c:
        c.connect({})
        assert c.connected
    assert not c.connected


def test_requires_connection() -> None:
    with pytest.raises(ConnectorError) as exc:
        make().list_schemas()
    assert exc.value.code is ErrorCode.NOT_CONNECTED
