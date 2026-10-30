from __future__ import annotations

import datetime as dt
import uuid

import duckdb

from magbi.connectors.base import SourceColumn, SourceTable
from magbi.connectors.types import DataType
from magbi.metadata.models import Dataset
from magbi.model.schema import (
    ColumnDef,
    DatasetDefinition,
    DateTableConfig,
    SqlTableSource,
    TableDef,
)
from magbi.refresh.dates import attach_date_table
from magbi.refresh.orchestrator import run_refresh
from tests.fakes import FakeConnector
from tests.test_refresh.test_orchestrator import Env


def orders() -> DatasetDefinition:
    return DatasetDefinition(
        connection_id=uuid.uuid4(),
        date_table=DateTableConfig(auto_generate=True),
        tables=[
            TableDef(
                name="orders",
                source=SqlTableSource.model_validate(
                    {"type": "table", "schema": "dbo", "table": "orders"}
                ),
                columns=[
                    ColumnDef(
                        name="id",
                        data_type=DataType.INTEGER,
                        is_primary_key=True,
                        is_nullable=False,
                    ),
                    ColumnDef(name="issued", data_type=DataType.DATE),
                    ColumnDef(name="paid", data_type=DataType.DATETIME),
                ],
            )
        ],
    )


def staging_with_orders() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE orders (id BIGINT, issued DATE, paid TIMESTAMP)")
    con.execute(
        "INSERT INTO orders VALUES (1, DATE '2024-02-29', TIMESTAMP '2024-06-15 12:00:00'), (2, NULL, NULL)"
    )
    return con


def test_date_table_covers_the_data_with_padding_and_one_active_link() -> None:
    con = staging_with_orders()
    result, updated = attach_date_table(con, orders())
    assert result is not None and result.rows > 366 and result.warnings == []
    span = con.execute(
        'SELECT MIN("Date"), MAX("Date"), COUNT(*) FROM "Date"'
    ).fetchone()
    assert span == (dt.date(2023, 2, 28), dt.date(2025, 6, 15), span[2])
    assert span[2] == (dt.date(2025, 6, 15) - dt.date(2023, 2, 28)).days + 1
    active = [r for r in updated.relationships if r.is_active]
    inactive = [r for r in updated.relationships if not r.is_active]
    assert [(r.from_.column, r.to.column) for r in active] == [("issued", "Date")]
    assert [r.from_.column for r in inactive] == ["paid"]
    assert updated.table("Date") is not None and updated.table("Date").is_date_table  # type: ignore[union-attr]


def test_second_attach_does_not_duplicate_relationships() -> None:
    con = staging_with_orders()
    _, once = attach_date_table(con, orders())
    _, twice = attach_date_table(con, once)
    assert len(twice.relationships) == len(once.relationships) == 2
    assert con.execute('SELECT COUNT(*) FROM "Date"').fetchone() == (
        (dt.date(2025, 6, 15) - dt.date(2023, 2, 28)).days + 1,
    )


def test_skipped_when_there_is_nothing_to_cover() -> None:
    empty = DatasetDefinition(date_table=DateTableConfig(auto_generate=True))
    result, same = attach_date_table(duckdb.connect(":memory:"), empty)
    assert result is not None and result.rows == 0 and result.warnings
    assert same.tables == []
    off = orders().model_copy(update={"date_table": DateTableConfig()})
    assert attach_date_table(duckdb.connect(":memory:"), off)[0] is None


def _connector() -> FakeConnector:
    table = SourceTable(
        schema="dbo",
        name="orders",
        columns=[
            SourceColumn("id", "int", is_nullable=False, is_primary_key=True),
            SourceColumn("issued", "date"),
            SourceColumn("paid", "datetime2"),
        ],
    )
    rows = [
        (1, dt.date(2024, 2, 29), dt.datetime(2024, 6, 15, 12, 0)),
        (2, None, None),
    ]
    return FakeConnector([table], {"dbo.orders": rows})


async def test_refresh_writes_the_date_table_into_live(tmp_path) -> None:
    env = Env(tmp_path, _connector())
    await env.setup()
    model = orders().model_copy(update={"connection_id": env.connection_id})
    async with env.sessions() as session:
        dataset = await session.get(Dataset, env.dataset_id)
        assert dataset is not None
        dataset.definition = model.model_dump(mode="json", by_alias=True)
        await session.commit()
    try:
        await run_refresh(env.deps, await env.queue())
        live = duckdb.connect(
            str(env.store.live_path(str(env.dataset_id))), read_only=True
        )
        try:
            count = live.execute('SELECT COUNT(*) FROM "Date"').fetchone()
            assert count == ((dt.date(2025, 6, 15) - dt.date(2023, 2, 28)).days + 1,)
            assert live.execute("SELECT COUNT(*) FROM orders").fetchone() == (2,)
        finally:
            live.close()
        async with env.sessions() as session:
            dataset = await session.get(Dataset, env.dataset_id)
            assert dataset is not None and dataset.definition is not None
            stored = DatasetDefinition.model_validate(dataset.definition)
            assert stored.table("Date") is not None
            assert any(
                r.is_active and r.from_.column == "issued" for r in stored.relationships
            )
    finally:
        await env.engine.dispose()
