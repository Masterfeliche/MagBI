from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from magbi.metadata.db import create_engine, create_session_factory
from magbi.metadata.models import (
    Base,
    Connection,
    Dataset,
    DatasetRefresh,
    RefreshStatus,
    Workspace,
)


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    eng = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


async def make_dataset(s: AsyncSession) -> Dataset:
    ws = Workspace(name="w")
    s.add(ws)
    await s.flush()
    ds = Dataset(workspace_id=ws.id, name="d")
    s.add(ds)
    await s.flush()
    return ds


async def test_connection_roundtrip_and_unique_name(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as s:
        ws = Workspace(name="w")
        s.add(ws)
        await s.flush()
        s.add(
            Connection(
                workspace_id=ws.id,
                name="erp",
                kind="sqlserver",
                config={"host": "h"},
                secret_encrypted="v1:abc",
            )
        )
        await s.commit()
        got = (await s.execute(select(Connection))).scalar_one()
        assert got.config == {"host": "h"} and got.secret_encrypted == "v1:abc"
        s.add(Connection(workspace_id=ws.id, name="erp", kind="sqlserver", config={}))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_definition_defaults_to_null_and_roundtrips(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as s:
        ds = await make_dataset(s)
        assert ds.definition is None and ds.model_version == 1
        ds.definition = {"schema_version": "1.0", "tables": []}
        await s.commit()
        again = (await s.execute(select(Dataset))).scalar_one()
        assert again.definition == {"schema_version": "1.0", "tables": []}


async def test_only_one_active_refresh_per_dataset(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as s:
        ds = await make_dataset(s)
        s.add(DatasetRefresh(dataset_id=ds.id, status=RefreshStatus.RUNNING))
        await s.commit()
        s.add(DatasetRefresh(dataset_id=ds.id))  # queued
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_finished_refreshes_do_not_block_new_ones(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as s:
        ds = await make_dataset(s)
        s.add_all(
            [
                DatasetRefresh(dataset_id=ds.id, status=RefreshStatus.SUCCEEDED),
                DatasetRefresh(dataset_id=ds.id, status=RefreshStatus.FAILED),
                DatasetRefresh(dataset_id=ds.id, status=RefreshStatus.FAILED),
                DatasetRefresh(dataset_id=ds.id, status=RefreshStatus.QUEUED),
            ]
        )
        await s.commit()


async def test_deleting_dataset_cascades_refreshes(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as s:
        ds = await make_dataset(s)
        s.add(DatasetRefresh(dataset_id=ds.id))
        await s.commit()
        await s.delete(ds)
        await s.commit()
        assert (await s.execute(select(DatasetRefresh))).first() is None
