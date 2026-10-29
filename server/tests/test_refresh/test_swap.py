from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import duckdb
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from magbi.metadata.db import create_engine, create_session_factory
from magbi.metadata.models import Base, Dataset, Workspace
from magbi.refresh.swap import SwapError, publish_version, swap_with_retry
from magbi.storage.duckdb_store import DuckDBStore

DS = "ds1"


@pytest.fixture
def store(tmp_path: Path) -> DuckDBStore:
    return DuckDBStore(tmp_path / "data", archive_versions=2)


def write_staging(store: DuckDBStore, value: int) -> None:
    con = store.open_staging(DS)
    con.execute("CREATE OR REPLACE TABLE t AS SELECT ? AS v", [value])
    con.close()


def live_value(store: DuckDBStore) -> int:
    con = store.open_live(DS)
    try:
        row = con.execute("SELECT v FROM t").fetchone()
        assert row is not None
        return int(row[0])
    finally:
        con.close()


def test_first_swap_makes_staging_live(store: DuckDBStore) -> None:
    write_staging(store, 1)
    assert swap_with_retry(store, DS) is None
    assert live_value(store) == 1
    assert not store.staging_path(DS).exists()


def test_second_swap_archives_previous(store: DuckDBStore) -> None:
    write_staging(store, 1)
    swap_with_retry(store, DS)
    write_staging(store, 2)
    assert swap_with_retry(store, DS) == 1
    assert live_value(store) == 2
    assert store.list_versions(DS) == [1]


def test_missing_staging_fails_fast_without_retrying(store: DuckDBStore) -> None:
    sleeps: list[float] = []
    with pytest.raises(SwapError, match="no staging"):
        swap_with_retry(store, DS, sleep=sleeps.append)
    assert sleeps == []


def test_transient_failure_is_retried_with_backoff(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_staging(store, 1)
    swap_with_retry(store, DS)
    write_staging(store, 2)

    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src: object, dst: object) -> None:
        calls["n"] += 1
        if calls["n"] <= 2:  # the first two attempts hit "file in use"
            raise PermissionError("in use")
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr("magbi.storage.duckdb_store.os.replace", flaky)
    sleeps: list[float] = []
    swap_with_retry(store, DS, base_delay=0.1, sleep=sleeps.append)
    assert sleeps == [0.1, 0.2]
    assert live_value(store) == 2


def test_permanent_failure_keeps_old_live_and_discards_staging(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_staging(store, 1)
    swap_with_retry(store, DS)
    write_staging(store, 2)

    real_replace = os.replace

    def fail_promote(src: object, dst: object) -> None:
        if (
            Path(str(dst)).name == "live.duckdb"
            and Path(str(src)).name == "staging.duckdb"
        ):
            raise PermissionError("in use")
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr("magbi.storage.duckdb_store.os.replace", fail_promote)
    sleeps: list[float] = []
    with pytest.raises(SwapError, match="previous version is still live"):
        swap_with_retry(store, DS, attempts=3, sleep=sleeps.append)
    assert len(sleeps) == 2
    assert live_value(store) == 1  # untouched
    assert not store.staging_path(DS).exists()  # cleaned up


def test_backoff_is_capped(store: DuckDBStore, monkeypatch: pytest.MonkeyPatch) -> None:
    write_staging(store, 1)
    monkeypatch.setattr(
        store,
        "promote_staging",
        lambda _id: (_ for _ in ()).throw(
            __import__(
                "magbi.storage.duckdb_store", fromlist=["StoreError"]
            ).StoreError("x")
        ),
    )
    sleeps: list[float] = []
    with pytest.raises(SwapError):
        swap_with_retry(store, DS, attempts=8, base_delay=1.0, sleep=sleeps.append)
    assert sleeps == [1.0, 2.0, 4.0, 5.0, 5.0, 5.0, 5.0]


def test_invalid_attempts(store: DuckDBStore) -> None:
    with pytest.raises(ValueError):
        swap_with_retry(store, DS, attempts=0)


def test_open_reader_keeps_its_snapshot_across_a_swap(store: DuckDBStore) -> None:
    # DuckDB lets the file be renamed while a reader has it open, so the swap succeeds
    # and the reader is undisturbed. NOTE: DuckDB caches open databases per path inside
    # a process, so new connections keep seeing the old data until every old connection
    # is closed. The query engine (Sprint 4) must close its live connections when a
    # dataset's current_version changes.
    write_staging(store, 1)
    swap_with_retry(store, DS)
    write_staging(store, 2)
    reader = store.open_live(DS)
    swap_with_retry(store, DS, attempts=1)
    assert reader.execute("SELECT v FROM t").fetchone() == (1,)
    reader.close()
    assert live_value(store) == 2


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    eng = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


async def test_publish_version_updates_current_version(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    store = DuckDBStore(tmp_path / "data")
    async with factory() as s:
        ws = Workspace(name="w")
        s.add(ws)
        await s.flush()
        ds = Dataset(workspace_id=ws.id, name="d")
        s.add(ds)
        await s.commit()
        dataset_id = ds.id

        con = store.open_staging(str(dataset_id))
        con.execute("CREATE TABLE t AS SELECT 1 AS v")
        con.close()
        await publish_version(s, store, dataset_id, 1)
        assert (await s.execute(select(Dataset.current_version))).scalar_one() == 1
        assert duckdb.connect(str(store.live_path(str(dataset_id))), read_only=True)


async def test_publish_version_leaves_version_unchanged_on_swap_failure(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    factory = create_session_factory(engine)
    store = DuckDBStore(tmp_path / "data")
    async with factory() as s:
        ws = Workspace(name="w")
        s.add(ws)
        await s.flush()
        ds = Dataset(workspace_id=ws.id, name="d", current_version=4)
        s.add(ds)
        await s.commit()
        with pytest.raises(SwapError):  # no staging file exists
            await publish_version(s, store, ds.id, 5)
        s.expire_all()
        assert (await s.execute(select(Dataset.current_version))).scalar_one() == 4
