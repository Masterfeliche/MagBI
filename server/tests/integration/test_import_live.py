"""Import real SQL Server tables into DuckDB and query them with plain SQL."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import duckdb
import pytest

from magbi.connectors.sqlserver import SqlServerConnector
from magbi.refresh.importer import TableSpec, import_tables

pytestmark = pytest.mark.integration


@pytest.fixture
def staging() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:")


def test_import_seed_tables(
    connector: SqlServerConnector, staging: duckdb.DuckDBPyConnection
) -> None:
    seen: list[int] = []
    result = import_tables(
        connector,
        [
            TableSpec("dbo", "all_types", "all_types"),
            TableSpec("dbo", "exotic_types", "exotic_types"),
            TableSpec("sales", "Order Lines", "order_lines"),
            TableSpec("sales", "big_lines", "big_lines"),
            TableSpec("dbo", "empty_table", "empty_table"),
        ],
        staging,
        progress=lambda _t, rows: seen.append(rows),
    )
    rows = {t.target: t.rows for t in result.tables}
    assert rows["all_types"] == 3 and rows["exotic_types"] == 2
    assert rows["order_lines"] == 200_000 and rows["empty_table"] == 0
    assert rows["big_lines"] > 0
    assert max(seen) == 200_000  # progress reported while streaming
    assert any("geography" in w.lower() or "c_geo" in w for w in result.warnings)

    # Counts and values match the source, queried with plain DuckDB SQL.
    assert staging.execute("SELECT count(*) FROM order_lines").fetchone() == (200_000,)
    assert staging.execute(
        'SELECT count(*), sum("Qty"), count("Note") FROM order_lines'
    ).fetchone() == (200_000, sum(i % 7 for i in range(1, 200_001)), 180_000)

    full = staging.execute("SELECT * FROM all_types WHERE id = 1").fetchone()
    assert full is not None
    assert full[1] == 9223372036854775807
    assert full[6] == Decimal("12345678901234.56")
    assert full[16] == "héllo wörld"
    assert full[18] == dt.date(2024, 2, 29)
    nulls = staging.execute("SELECT * FROM all_types WHERE id = 2").fetchone()
    assert nulls is not None and all(v is None for v in nulls[1:])
    assert staging.execute(
        "SELECT c_nvarchar FROM all_types WHERE id = 3"
    ).fetchone() == ("日本語 😀 Ж",)
    assert staging.execute(
        "SELECT c_hier, c_variant, c_xml FROM exotic_types WHERE id = 1"
    ).fetchone() == ("/1/2/", "42", "<a>1</a>")
