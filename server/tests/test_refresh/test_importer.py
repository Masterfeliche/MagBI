from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import duckdb
import pytest

from magbi.connectors.base import SourceColumn, SourceTable
from magbi.connectors.errors import ConnectorError, ErrorCode
from magbi.refresh.importer import (
    ImportPipelineError,
    TableSpec,
    import_tables,
    quote_ident,
)
from tests.fakes import FakeConnector


def col(name: str, data_type: str, **kw: Any) -> SourceColumn:
    return SourceColumn(name=name, data_type=data_type, **kw)


def table(name: str, *cols: SourceColumn, schema: str = "dbo") -> SourceTable:
    return SourceTable(schema=schema, name=name, columns=list(cols))


@pytest.fixture
def staging() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:")


def connected(
    tables: list[SourceTable], rows: dict[str, list[tuple[Any, ...]]], **kw: Any
) -> FakeConnector:
    c = FakeConnector(tables, rows, **kw)
    c.connect({})
    return c


def test_imports_rows_with_types_and_nulls(staging: duckdb.DuckDBPyConnection) -> None:
    t = table(
        "t",
        col("id", "bigint"),
        col("amount", "decimal(10,2)", precision=10, scale=2),
        col("name", "nvarchar(20)"),
        col("born", "date"),
        col("at", "datetime2"),
        col("ok", "bit"),
        col("blob", "varbinary(8)"),
    )
    rows = [
        (
            1,
            Decimal("12.34"),
            "héllo",
            dt.date(2024, 1, 2),
            dt.datetime(2024, 1, 2, 3, 4, 5, 6),
            True,
            b"\x01",
        ),
        (2, None, None, None, None, None, None),
    ]
    c = connected([t], {"dbo.t": rows})
    result = import_tables(c, [TableSpec("dbo", "t", "t")], staging)

    assert result.total_rows == 2 and result.warnings == []
    got = staging.execute("SELECT * FROM t ORDER BY id").fetchall()
    assert got == [tuple(rows[0]), tuple(rows[1])]
    types = {r[0]: r[1] for r in staging.execute("DESCRIBE t").fetchall()}
    assert types["id"] == "BIGINT" and types["amount"] == "DECIMAL(10,2)"
    assert (
        types["born"] == "DATE" and types["ok"] == "BOOLEAN" and types["blob"] == "BLOB"
    )


def test_batches_and_progress(staging: duckdb.DuckDBPyConnection) -> None:
    t = table("t", col("id", "int"))
    rows = [(i,) for i in range(25)]
    c = connected([t], {"dbo.t": rows})
    seen: list[tuple[str, int]] = []
    result = import_tables(
        c,
        [TableSpec("dbo", "t", "out")],
        staging,
        batch_size=10,
        progress=lambda n, r: seen.append((n, r)),
    )
    assert seen == [("out", 10), ("out", 20), ("out", 25)]
    assert result.tables[0].rows == 25
    assert staging.execute("SELECT count(*), sum(id) FROM out").fetchone() == (25, 300)


def test_empty_table_creates_empty_target(staging: duckdb.DuckDBPyConnection) -> None:
    c = connected([table("t", col("id", "int"))], {"dbo.t": []})
    result = import_tables(c, [TableSpec("dbo", "t", "t")], staging)
    assert result.total_rows == 0
    assert staging.execute("SELECT count(*) FROM t").fetchone() == (0,)


def test_multiple_tables_in_order(staging: duckdb.DuckDBPyConnection) -> None:
    ts = [table("a", col("x", "int")), table("b", col("y", "int"), schema="sales")]
    c = connected(ts, {"dbo.a": [(1,)], "sales.b": [(2,), (3,)]})
    result = import_tables(
        c, [TableSpec("dbo", "a", "a"), TableSpec("sales", "b", "sales_b")], staging
    )
    assert [t.rows for t in result.tables] == [1, 2]
    assert staging.execute("SELECT count(*) FROM sales_b").fetchone() == (2,)


def test_hostile_names_are_quoted(staging: duckdb.DuckDBPyConnection) -> None:
    t = table("t", col('we"ird col', "int"))
    c = connected([t], {"dbo.t": [(7,)]})
    import_tables(c, [TableSpec("dbo", "t", 'ta"rget; DROP TABLE x')], staging)
    col_sql = quote_ident('we"ird col')
    tbl_sql = quote_ident('ta"rget; DROP TABLE x')
    got = staging.execute(f"SELECT {col_sql} FROM {tbl_sql}").fetchall()
    assert got == [(7,)]


def test_warnings_for_degraded_types(staging: duckdb.DuckDBPyConnection) -> None:
    t = table(
        "t",
        col("id", "int"),
        col("g", "geography"),
        col("big", "decimal(38,0)", precision=38, scale=0),
    )
    c = connected([t], {"dbo.t": [(1, "POINT(1 2)", Decimal(5))]})
    result = import_tables(c, [TableSpec("dbo", "t", "t")], staging)
    assert any("g" in w for w in result.warnings)
    assert staging.execute("SELECT g FROM t").fetchone() == ("POINT(1 2)",)


def test_decimal_above_38_digits_becomes_double(
    staging: duckdb.DuckDBPyConnection,
) -> None:
    t = table("t", col("v", "decimal(40,2)", precision=40, scale=2))
    c = connected([t], {"dbo.t": [(Decimal("123.45"),), (None,)]})
    result = import_tables(c, [TableSpec("dbo", "t", "t")], staging)
    assert staging.execute("SELECT v FROM t ORDER BY v NULLS LAST").fetchall() == [
        (123.45,),
        (None,),
    ]
    assert result.warnings


def test_row_count_change_is_a_warning_not_a_failure(
    staging: duckdb.DuckDBPyConnection,
) -> None:
    class Growing(FakeConnector):
        def get_row_count(self, schema: str, table: str) -> int:
            return super().get_row_count(schema, table) - 1

    c = Growing([table("t", col("id", "int"))], {"dbo.t": [(1,), (2,)]})
    c.connect({})
    result = import_tables(c, [TableSpec("dbo", "t", "t")], staging)
    assert result.total_rows == 2
    assert any("changed during import" in w for w in result.warnings)


def test_missing_source_table_is_not_found(staging: duckdb.DuckDBPyConnection) -> None:
    c = connected([], {})
    with pytest.raises(ConnectorError) as exc:
        import_tables(c, [TableSpec("dbo", "nope", "nope")], staging)
    assert exc.value.code == ErrorCode.NOT_FOUND


def test_source_failure_mid_stream_propagates(
    staging: duckdb.DuckDBPyConnection,
) -> None:
    c = connected(
        [table("t", col("id", "int"))],
        {"dbo.t": [(i,) for i in range(30)]},
        fail_after_rows=15,
    )
    with pytest.raises(ConnectorError) as exc:
        import_tables(c, [TableSpec("dbo", "t", "t")], staging, batch_size=10)
    assert exc.value.code == ErrorCode.UNREACHABLE


def test_unconvertible_value_gives_clear_error(
    staging: duckdb.DuckDBPyConnection,
) -> None:
    c = connected([table("t", col("id", "int"))], {"dbo.t": [(1,), ("not a number",)]})
    with pytest.raises(ImportPipelineError) as exc:
        import_tables(c, [TableSpec("dbo", "t", "t")], staging)
    assert "could not be converted" in str(exc.value)
    assert "not a number" not in str(exc.value)  # no data in messages


@pytest.mark.parametrize(
    ("specs", "message"),
    [
        ([], "nothing to import"),
        ([TableSpec("dbo", "t", "")], "target table name"),
        ([TableSpec("dbo", "t", "x" * 200)], "target table name"),
        ([TableSpec("dbo", "t", "a\nb")], "control characters"),
        ([TableSpec("dbo", "t", "Same"), TableSpec("dbo", "u", "same")], "duplicate"),
    ],
)
def test_invalid_specs_rejected_before_any_work(
    staging: duckdb.DuckDBPyConnection, specs: list[TableSpec], message: str
) -> None:
    c = connected([table("t", col("id", "int"))], {"dbo.t": [(1,)]})
    with pytest.raises(ImportPipelineError, match=message):
        import_tables(c, specs, staging)
    assert c.queries == []


def test_result_to_dict(staging: duckdb.DuckDBPyConnection) -> None:
    c = connected([table("t", col("id", "int"))], {"dbo.t": [(1,)]})
    d = import_tables(c, [TableSpec("dbo", "t", "t")], staging).to_dict()
    assert d["total_rows"] == 1 and d["tables"][0]["target"] == "t"
    assert isinstance(d["tables"][0]["seconds"], float)
