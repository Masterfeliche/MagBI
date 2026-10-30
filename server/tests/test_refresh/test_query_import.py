"""Tables built from read-only SQL queries, and uploads that survive a refresh."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import duckdb
import pytest

from magbi.connectors.base import SourceColumn
from magbi.connectors.errors import ConnectorError
from magbi.refresh.file_import import carry_over_tables
from magbi.refresh.importer import ImportPipelineError, TableSpec, import_tables
from magbi.refresh.orchestrator import _import_plan
from magbi.storage.duckdb_store import DuckDBStore
from tests.fakes import FakeConnector

BATCH_SQL = "SELECT BatchID, ExpDate, DaysLeft FROM wms.SKUBatch WHERE QtyOnHand > 0"


def _connector(**results: tuple[list[SourceColumn], list[tuple[object, ...]]]) -> FakeConnector:
    fake = FakeConnector(query_results=dict(results))
    fake.connect({})
    return fake


def test_a_query_table_imports_with_the_query_column_types() -> None:
    columns = [
        SourceColumn("BatchID", "varchar", max_length=36),
        SourceColumn("ExpDate", "date"),
        SourceColumn("DaysLeft", "int"),
    ]
    rows = [("b1", dt.date(2026, 11, 3), 4), ("b2", None, None)]
    fake = _connector(**{BATCH_SQL: (columns, rows)})
    staging = duckdb.connect()
    result = import_tables(fake, [TableSpec("", "Batch", "Batch", query=BATCH_SQL)], staging)
    assert result.tables[0].rows == 2
    assert staging.execute('SELECT * FROM "Batch" ORDER BY "BatchID"').fetchall() == [
        ("b1", dt.date(2026, 11, 3), 4),
        ("b2", None, None),
    ]
    types = dict(staging.execute("SELECT column_name, data_type FROM information_schema.columns").fetchall())
    assert types == {"BatchID": "VARCHAR", "ExpDate": "DATE", "DaysLeft": "BIGINT"}
    assert fake.queries == [BATCH_SQL]


def test_a_query_that_writes_is_refused_before_it_runs() -> None:
    sql = "SELECT a INTO copy FROM t"
    fake = _connector(**{sql: ([SourceColumn("a", "int")], [(1,)])})
    with pytest.raises(ConnectorError, match="INTO"):
        import_tables(fake, [TableSpec("", "Copy", "Copy", query=sql)], duckdb.connect())
    assert fake.queries == []


def test_a_query_column_that_needs_a_cast_asks_for_it_in_the_query() -> None:
    sql = "SELECT shape FROM geo"
    fake = _connector(**{sql: ([SourceColumn("shape", "geography")], [])})
    with pytest.raises(ImportPipelineError, match="shape"):
        import_tables(fake, [TableSpec("", "Geo", "Geo", query=sql)], duckdb.connect())


def test_the_refresh_plan_imports_queries_and_skips_uploads() -> None:
    connection = uuid.uuid4()
    raw = {
        "connection_id": str(connection),
        "tables": [
            {"name": "Batch", "source": {"type": "query", "sql": BATCH_SQL}, "columns": [{"name": "BatchID", "data_type": "string"}]},
            {"name": "Orders", "source": {"type": "table", "schema": "dbo", "table": "orders"}, "columns": [{"name": "id", "data_type": "integer"}]},
            {"name": "Budget", "source": {"type": "csv", "file_path": "uploads/Budget.csv"}, "columns": [{"name": "Amount", "data_type": "decimal"}]},
        ],
    }
    found, specs = _import_plan(raw)
    assert found == connection
    assert specs == [
        TableSpec("", "Batch", "Batch", query=BATCH_SQL),
        TableSpec("dbo", "orders", "Orders"),
    ]


def test_uploaded_tables_are_carried_into_the_new_version(tmp_path: Path) -> None:
    store = DuckDBStore(tmp_path)
    dataset = str(uuid.uuid4())
    live = store.live_path(dataset)
    live.parent.mkdir(parents=True, exist_ok=True)
    seed = duckdb.connect(str(live))
    seed.execute('CREATE TABLE "Budget" ("Amount" DECIMAL(10,2))')
    seed.execute('INSERT INTO "Budget" VALUES (12.50), (7.25)')
    seed.execute('CREATE TABLE "Orders" ("id" INTEGER)')
    seed.close()
    staging = duckdb.connect()
    carry_over_tables(store, dataset, staging, ["Budget", "Missing"])
    assert staging.execute('SELECT CAST(SUM("Amount") AS DOUBLE) FROM "Budget"').fetchone() == (19.75,)
    tables = {row[0] for row in staging.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    assert tables == {"Budget"}
