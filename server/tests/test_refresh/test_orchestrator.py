from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import duckdb
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from magbi.connections import ConnectionService
from magbi.connectors.base import SourceColumn, SourceTable
from magbi.connectors.errors import ConnectorError, ErrorCode
from magbi.metadata.db import create_engine, create_session_factory
from magbi.metadata.models import (
    Base,
    Connection,
    Dataset,
    DatasetRefresh,
    RefreshStatus,
    Workspace,
)
from magbi.model.schema import definition_from_import_spec
from magbi.refresh.orchestrator import (
    RefreshConflict,
    RefreshDeps,
    queue_refresh,
    run_refresh,
    sanitize_error,
    sweep_stale_refreshes,
)
from magbi.storage.credentials import CredentialVault, generate_key
from magbi.storage.duckdb_store import DuckDBStore
from tests.fakes import FakeConnector

PASSWORD = "Sup3r;Secret"
CFG = {
    "host": "db",
    "database": "erp",
    "authentication": "sql",
    "username": "bi",
    "password": PASSWORD,
}
TABLE = SourceTable(
    schema="dbo",
    name="orders",
    columns=[SourceColumn("id", "int"), SourceColumn("name", "nvarchar(20)")],
)


class Env:
    def __init__(self, tmp: Path, fake: FakeConnector) -> None:
        self.fake = fake
        self.vault = CredentialVault.from_encoded_key(generate_key())
        self.service = ConnectionService(
            self.vault, connectors={"sqlserver": lambda: self.fake}
        )
        self.store = DuckDBStore(tmp / "data")
        self.engine: AsyncEngine = create_engine(f"sqlite+aiosqlite:///{tmp / 'm.db'}")
        self.sessions: async_sessionmaker[AsyncSession] = create_session_factory(
            self.engine
        )
        self.deps = RefreshDeps(self.sessions, self.store, self.service, batch_size=10)
        self.dataset_id: uuid.UUID
        self.connection_id: uuid.UUID

    async def setup(self, import_spec: dict[str, Any] | None = None) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with self.sessions() as s:
            ws = Workspace(name="w")
            s.add(ws)
            await s.flush()
            cid = uuid.uuid4()
            public, secret = self.service.prepare("sqlserver", CFG, connection_id=cid)
            s.add(
                Connection(
                    id=cid,
                    workspace_id=ws.id,
                    name="erp",
                    kind="sqlserver",
                    config=public,
                    secret_encrypted=secret,
                )
            )
            spec = (
                import_spec
                if import_spec is not None
                else {
                    "connection_id": str(cid),
                    "tables": [{"schema": "dbo", "name": "orders", "target": "orders"}],
                }
            )
            try:
                stored = definition_from_import_spec(spec).model_dump(
                    mode="json", by_alias=True
                )
            except (KeyError, ValueError):
                stored = spec  # deliberately not a definition; the refresh must say so
            ds = Dataset(workspace_id=ws.id, name="d", definition=stored)
            s.add(ds)
            await s.commit()
            self.dataset_id, self.connection_id = ds.id, cid

    async def queue(self) -> uuid.UUID:
        async with self.sessions() as s:
            return (await queue_refresh(s, self.dataset_id)).id

    async def refresh(self, refresh_id: uuid.UUID) -> DatasetRefresh:
        async with self.sessions() as s:
            r = await s.get(DatasetRefresh, refresh_id)
            assert r is not None
            return r

    async def current_version(self) -> int:
        async with self.sessions() as s:
            return (
                await s.execute(
                    select(Dataset.current_version).where(Dataset.id == self.dataset_id)
                )
            ).scalar_one()


def fake(rows: int = 25, **kw: Any) -> FakeConnector:
    return FakeConnector(
        [TABLE], {"dbo.orders": [(i, f"n{i}") for i in range(rows)]}, **kw
    )


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[Env]:
    e = Env(tmp_path, fake())
    await e.setup()
    yield e
    await e.engine.dispose()


def live_rows(env: Env) -> int:
    con = duckdb.connect(str(env.store.live_path(str(env.dataset_id))), read_only=True)
    try:
        row = con.execute("SELECT count(*) FROM orders").fetchone()
        assert row is not None
        return int(row[0])
    finally:
        con.close()


async def test_successful_refresh(env: Env) -> None:
    rid = await env.queue()
    await run_refresh(env.deps, rid)
    r = await env.refresh(rid)
    assert r.status is RefreshStatus.SUCCEEDED and r.error is None
    assert r.version == 1 and r.started_at and r.finished_at
    assert r.result and r.result["total_rows"] == 25 and r.result["version"] == 1
    assert await env.current_version() == 1
    assert live_rows(env) == 25
    assert not env.store.staging_path(str(env.dataset_id)).exists()
    assert env.fake.close_calls == 1


async def test_second_refresh_bumps_version_and_archives(env: Env) -> None:
    await run_refresh(env.deps, await env.queue())
    env.fake.rows["dbo.orders"].append((99, "new"))
    rid = await env.queue()
    await run_refresh(env.deps, rid)
    assert (await env.refresh(rid)).version == 2
    assert await env.current_version() == 2
    assert live_rows(env) == 26
    assert env.store.list_versions(str(env.dataset_id)) == [1]


async def test_source_failure_marks_failed_and_keeps_old_data(env: Env) -> None:
    await run_refresh(env.deps, await env.queue())
    env.fake.fail_after_rows = 5
    rid = await env.queue()
    await run_refresh(env.deps, rid)
    r = await env.refresh(rid)
    assert r.status is RefreshStatus.FAILED
    assert r.error and "connection lost" in r.error
    assert await env.current_version() == 1  # unchanged
    assert live_rows(env) == 25  # old data still served
    assert not env.store.staging_path(str(env.dataset_id)).exists()
    assert env.fake.close_calls == 2  # connector closed on failure too


async def test_connect_failure_is_reported(tmp_path: Path) -> None:
    e = Env(
        tmp_path, fake(fail_connect=ConnectorError(ErrorCode.AUTH_FAILED, "bad login"))
    )
    await e.setup()
    try:
        rid = await e.queue()
        await run_refresh(e.deps, rid)
        r = await e.refresh(rid)
        assert r.status is RefreshStatus.FAILED and "AUTH_FAILED" in (r.error or "")
        assert not e.store.exists(str(e.dataset_id))
    finally:
        await e.engine.dispose()


async def test_password_in_error_is_redacted(tmp_path: Path) -> None:
    leaky = ConnectorError(ErrorCode.QUERY_FAILED, f"failed with pwd {PASSWORD} here")
    e = Env(tmp_path, fake(fail_connect=leaky))
    await e.setup()
    try:
        rid = await e.queue()
        await run_refresh(e.deps, rid)
        r = await e.refresh(rid)
        assert r.error and PASSWORD not in r.error and "***" in r.error
    finally:
        await e.engine.dispose()


async def test_unexpected_error_is_not_leaked(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError(f"internal detail {PASSWORD} /srv/path")

    monkeypatch.setattr("magbi.refresh.orchestrator.import_tables", boom)
    rid = await env.queue()
    await run_refresh(env.deps, rid)
    r = await env.refresh(rid)
    assert r.status is RefreshStatus.FAILED
    assert r.error == "unexpected error (RuntimeError); see server log"


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({}, "no tables configured"),
        ({"tables": [{"schema": "dbo"}]}, "definition is invalid"),
        ({"tables": [{"schema": "dbo", "name": "orders"}]}, "no connection configured"),
        (
            {
                "connection_id": str(uuid.uuid4()),
                "tables": [{"schema": "dbo", "name": "orders"}],
            },
            "connection was not found",
        ),
    ],
)
async def test_bad_import_spec_fails_cleanly(
    tmp_path: Path, spec: dict[str, Any], message: str
) -> None:
    e = Env(tmp_path, fake())
    await e.setup(import_spec=spec)
    try:
        rid = await e.queue()
        await run_refresh(e.deps, rid)
        r = await e.refresh(rid)
        assert r.status is RefreshStatus.FAILED and message in (r.error or "")
    finally:
        await e.engine.dispose()


async def test_missing_source_table_fails_with_not_found(tmp_path: Path) -> None:
    e = Env(tmp_path, FakeConnector([], {}))
    await e.setup()
    try:
        rid = await e.queue()
        await run_refresh(e.deps, rid)
        assert "NOT_FOUND" in ((await e.refresh(rid)).error or "")
    finally:
        await e.engine.dispose()


async def test_only_one_active_refresh(env: Env) -> None:
    first = await env.queue()
    with pytest.raises(RefreshConflict) as exc:
        await env.queue()
    assert exc.value.refresh_id == first
    await run_refresh(env.deps, first)
    await env.queue()  # allowed again once the first finished


async def test_concurrent_queue_attempts_create_exactly_one(env: Env) -> None:
    async def attempt() -> str:
        async with env.sessions() as s:
            try:
                await queue_refresh(s, env.dataset_id)
                return "queued"
            except RefreshConflict:
                return "conflict"

    results = await asyncio.gather(*(attempt() for _ in range(5)))
    assert results.count("queued") == 1 and results.count("conflict") == 4


async def test_running_a_finished_or_unknown_refresh_is_a_noop(env: Env) -> None:
    rid = await env.queue()
    await run_refresh(env.deps, rid)
    await run_refresh(env.deps, rid)  # already succeeded
    await run_refresh(env.deps, uuid.uuid4())  # unknown
    assert (await env.refresh(rid)).version == 1
    assert env.fake.close_calls == 1


async def test_startup_sweep_fails_stale_refreshes(env: Env) -> None:
    async with env.sessions() as s:
        s.add(DatasetRefresh(dataset_id=env.dataset_id, status=RefreshStatus.RUNNING))
        await s.commit()
    con = env.store.open_staging(str(env.dataset_id))
    con.close()
    assert env.store.staging_path(str(env.dataset_id)).exists()

    assert await sweep_stale_refreshes(env.deps) == 1
    async with env.sessions() as s:
        r = (await s.execute(select(DatasetRefresh))).scalar_one()
        assert r.status is RefreshStatus.FAILED and "restart" in (r.error or "")
        assert r.finished_at is not None
    assert not env.store.staging_path(str(env.dataset_id)).exists()
    assert await sweep_stale_refreshes(env.deps) == 0
    await env.queue()  # dataset is unblocked


async def test_leftover_staging_from_a_crash_is_replaced(env: Env) -> None:
    con = env.store.open_staging(str(env.dataset_id))
    con.execute("CREATE TABLE junk AS SELECT 1")
    con.close()
    await run_refresh(env.deps, await env.queue())
    live = duckdb.connect(str(env.store.live_path(str(env.dataset_id))), read_only=True)
    try:
        names = {r[0] for r in live.execute("SHOW TABLES").fetchall()}
    finally:
        live.close()
    assert names == {"orders"}


def test_sanitize_error() -> None:
    assert sanitize_error("pw=abc here", ("abc",)) == "pw=*** here"
    assert sanitize_error("x", ("",)) == "x"
    assert len(sanitize_error("y" * 5000)) == 1000
