"""Connector behaviour against a real SQL Server 2022 (seeded by ``seed.sql``)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pyarrow as pa
import pytest

from magbi.connectors.base import SourceTable
from magbi.connectors.errors import ConnectorError, ErrorCode
from magbi.connectors.sqlserver import SqlServerConnector
from magbi.connectors.types import arrow_schema, cast_map, plan_columns, warnings

pytestmark = pytest.mark.integration


def load_arrow(c: SqlServerConnector, table: SourceTable) -> tuple[pa.Table, list[str]]:
    """Read a table the way the importer will: planned casts, planned Arrow schema."""
    plans = plan_columns(table.columns)
    sql = c.build_select(table, casts=cast_map(plans))
    rows = list(c.execute_query(sql))
    schema = arrow_schema(plans)
    columns = [
        pa.array([r[i] for r in rows], type=field.type)
        for i, field in enumerate(schema)
    ]
    return pa.Table.from_arrays(columns, schema=schema), warnings(plans)


def by_id(table: pa.Table) -> dict[int, dict[str, Any]]:
    return {row["id"]: row for row in table.to_pylist()}


# -- connection ---------------------------------------------------------------


def test_connection_reports_version_and_schemas(mssql_config: dict[str, Any]) -> None:
    result = SqlServerConnector().test_connection(mssql_config)
    assert result.success, result
    assert "SQL Server 2022" in (result.server_version or "")
    assert {"dbo", "sales"} <= set(result.schemas)
    assert "sys" not in result.schemas
    assert result.latency_ms is not None and result.latency_ms >= 0


def test_wrong_password_maps_to_auth_failed(mssql_config_factory: Any) -> None:
    result = SqlServerConnector().test_connection(
        mssql_config_factory(password="definitely-wrong")
    )
    assert not result.success
    assert result.code == ErrorCode.AUTH_FAILED
    assert "definitely-wrong" not in (result.error or "")


def test_unreachable_port_maps_to_unreachable(mssql_config_factory: Any) -> None:
    result = SqlServerConnector().test_connection(
        mssql_config_factory(port=1, connection_timeout=3)
    )
    assert not result.success
    assert result.code in {ErrorCode.UNREACHABLE, ErrorCode.TIMEOUT}


def test_unknown_database_is_reported(mssql_config_factory: Any) -> None:
    result = SqlServerConnector().test_connection(
        mssql_config_factory(database="no_such_db")
    )
    assert not result.success
    assert result.code in {ErrorCode.AUTH_FAILED, ErrorCode.NOT_FOUND}


def test_read_only_login_can_read_but_not_write(
    mssql_config_factory: Any,
) -> None:
    from tests.integration.conftest import RO_PASSWORD

    cfg = mssql_config_factory(username="magbi_ro", password=RO_PASSWORD)
    with SqlServerConnector() as c:
        c.connect(cfg)
        assert c.get_row_count("dbo", "all_types") == 3
        with pytest.raises(ConnectorError) as exc:
            list(c.execute_query("DELETE FROM dbo.all_types"))
        assert exc.value.code == ErrorCode.UNSUPPORTED


# -- catalog ------------------------------------------------------------------


def test_list_tables_with_keys_kinds_and_estimates(
    connector: SqlServerConnector,
) -> None:
    tables = {t.name: t for t in connector.list_tables("sales")}
    assert set(tables) == {"Order Lines", "composite_key", "big_lines"}
    lines = tables["Order Lines"]
    assert lines.kind == "table"
    assert tables["big_lines"].kind == "view"
    assert lines.estimated_rows == pytest.approx(200_000, rel=0.05)
    pk = {c.name for c in lines.columns if c.is_primary_key}
    assert pk == {"Line ID"}
    composite = {c.name for c in tables["composite_key"].columns if c.is_primary_key}
    assert composite == {"a", "b"}
    note = next(c for c in lines.columns if c.name == "Note")
    assert note.is_nullable and note.max_length == 50


def test_find_table_missing_raises_not_found(connector: SqlServerConnector) -> None:
    with pytest.raises(ConnectorError) as exc:
        connector.find_table("dbo", "nope")
    assert exc.value.code == ErrorCode.NOT_FOUND


# -- types --------------------------------------------------------------------


def test_every_mapped_type_round_trips_into_arrow(
    connector: SqlServerConnector,
) -> None:
    table = connector.find_table("dbo", "all_types")
    arrow, warns = load_arrow(connector, table)
    assert warns == []
    rows = by_id(arrow)

    full = rows[1]
    assert full["c_bigint"] == 9223372036854775807
    assert full["c_tinyint"] == 255
    assert full["c_bit"] is True
    assert full["c_decimal"] == Decimal("12345678901234.56")
    assert full["c_decimal_big"] == Decimal("1234567890123456789012345678.1234567890")
    assert full["c_money"] == Decimal("922337203685477.5807")
    assert full["c_float"] == pytest.approx(3.141592653589793)
    assert full["c_varchar"] == "hello"
    assert full["c_nvarchar"] == "héllo wörld"
    assert full["c_guid"].upper() == "6F9619FF-8B86-D011-B42D-00C04FC964FF"
    assert full["c_date"] == dt.date(2024, 2, 29)
    assert full["c_datetime2"] == dt.datetime(2024, 2, 29, 13, 14, 15, 123456)
    assert full["c_time"] == dt.time(13, 14, 15, 123456)
    assert full["c_varbinary"] == b"\xde\xad\xbe\xef"

    assert all(v is None for k, v in rows[2].items() if k != "id")  # NULLs survive

    edge = rows[3]
    assert edge["c_bigint"] == -9223372036854775808
    assert edge["c_nvarchar"] == "日本語 😀 Ж"
    assert edge["c_date"] == dt.date(1, 1, 1)
    assert edge["c_varchar"] == "" and edge["c_varbinary"] == b""


def test_unmapped_types_degrade_to_strings_with_warnings(
    connector: SqlServerConnector,
) -> None:
    table = connector.find_table("dbo", "exotic_types")
    arrow, warns = load_arrow(connector, table)
    assert len(warns) >= 5
    rows = by_id(arrow)

    assert rows[1]["c_xml"] == "<a>1</a>"
    assert rows[1]["c_hier"] == "/1/2/"
    assert rows[1]["c_variant"] == "42"
    assert rows[1]["c_geo"]  # textual form, content depends on the server
    # datetimeoffset is normalised to UTC (12:00 +03:00 -> 09:00); the 7th fractional
    # digit is rounded by SQL Server when narrowing to datetime2(6)
    assert rows[1]["c_dto"] == dt.datetime(2024, 3, 1, 9, 0, 0, 123457)
    assert all(v is None for k, v in rows[2].items() if k != "id")


# -- reading ------------------------------------------------------------------


def test_hostile_identifiers_are_quoted(connector: SqlServerConnector) -> None:
    table = connector.find_table("sales", "Order Lines")
    arrow, _ = load_arrow(connector, table)
    assert arrow.column_names == ["Line ID", "Qty", "Note", "a]b"]
    assert arrow.num_rows == 200_000
    assert set(arrow.column("a]b").to_pylist()) == {1}
    assert arrow.column("Note").null_count == 20_000


def test_large_table_streams_in_batches(connector: SqlServerConnector) -> None:
    table = connector.find_table("sales", "Order Lines")
    sql = connector.build_select(table)
    total = 0
    last = 0
    for row in connector.execute_query(sql, batch_size=5_000):
        total += 1
        last = row[0]
    assert total == 200_000
    assert connector.get_row_count("sales", "Order Lines") == total
    assert last > 0


def test_limit_and_preview(connector: SqlServerConnector) -> None:
    rows = list(connector.preview("sales", "Order Lines", limit=5))
    assert len(rows) == 5
    assert list(connector.preview("dbo", "empty_table")) == []


def test_view_is_readable(connector: SqlServerConnector) -> None:
    assert connector.get_row_count("sales", "big_lines") > 0


def test_non_select_is_rejected_before_reaching_the_server(
    connector: SqlServerConnector,
) -> None:
    with pytest.raises(ConnectorError):
        list(connector.execute_query("SELECT 1; DROP TABLE dbo.all_types"))
    assert connector.get_row_count("dbo", "all_types") == 3
