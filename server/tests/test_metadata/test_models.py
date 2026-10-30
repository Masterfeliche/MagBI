from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from magbi.metadata.db import (
    check_connection,
    create_engine,
    create_session_factory,
    session_scope,
)
from magbi.metadata.models import (
    AuditLog,
    Base,
    Dataset,
    DatasetMode,
    Report,
    Role,
    User,
    Workspace,
    WorkspaceMember,
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


@pytest.fixture
async def session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as s:
        yield s


async def count(session: AsyncSession, model: type[Base]) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def make_workspace(session: AsyncSession, name: str = "Finance") -> Workspace:
    ws = Workspace(name=name, description="d")
    session.add(ws)
    await session.flush()
    return ws


async def make_dataset(
    session: AsyncSession, ws: Workspace, name: str = "Invoices"
) -> Dataset:
    ds = Dataset(workspace_id=ws.id, name=name)
    session.add(ds)
    await session.flush()
    return ds


# -- create / read -----------------------------------------------------------


async def test_workspace_crud(session: AsyncSession) -> None:
    ws = await make_workspace(session)
    await session.commit()

    got = (await session.execute(select(Workspace))).scalar_one()
    assert got.id == ws.id and got.name == "Finance"
    assert got.created_at.tzinfo is not None

    got.name = "Finance 2"
    await session.commit()
    assert (await session.get(Workspace, ws.id)).name == "Finance 2"  # type: ignore[union-attr]

    await session.delete(got)
    await session.commit()
    assert await count(session, Workspace) == 0


async def test_dataset_defaults(session: AsyncSession) -> None:
    ds = await make_dataset(session, await make_workspace(session))
    await session.commit()
    assert ds.mode is DatasetMode.IMPORT
    assert ds.current_version == 0
    assert ds.schedule_cron is None
    assert ds.updated_at.tzinfo is not None


async def test_dataset_updated_at_changes(session: AsyncSession) -> None:
    ds = await make_dataset(session, await make_workspace(session))
    await session.commit()
    before = ds.updated_at
    ds.current_version = 1
    await session.commit()
    await session.refresh(ds)
    assert ds.updated_at >= before


async def test_report_json_round_trip(session: AsyncSession) -> None:
    ws = await make_workspace(session)
    ds = await make_dataset(session, ws)
    definition = {"pages": [{"name": "p1", "visuals": [{"type": "bar", "x": 1.5}]}]}
    session.add(
        Report(workspace_id=ws.id, dataset_id=ds.id, name="R", definition=definition)
    )
    await session.commit()
    session.expunge_all()

    got = (await session.execute(select(Report))).scalar_one()
    assert got.definition == definition
    assert got.is_published is False


async def test_user_and_membership(session: AsyncSession) -> None:
    ws = await make_workspace(session)
    user = User(email="a@x.com", name="A")
    session.add(user)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=Role.EDITOR))
    await session.commit()
    session.expunge_all()

    member = (await session.execute(select(WorkspaceMember))).scalar_one()
    assert member.role is Role.EDITOR
    assert user.is_active is True
    assert user.password_hash is None


async def test_audit_log_autoincrement_and_json(session: AsyncSession) -> None:
    for i in range(2):
        session.add(
            AuditLog(
                principal="a@x.com",
                action="dataset.create",
                object_type="dataset",
                object_id=str(i),
                detail={"n": i},
            )
        )
    await session.commit()
    rows = (
        (await session.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()
    )
    assert [r.id for r in rows] == [1, 2]
    assert rows[1].detail == {"n": 1}
    assert rows[0].at.tzinfo is not None


# -- constraints -------------------------------------------------------------


async def test_unique_workspace_name(session: AsyncSession) -> None:
    await make_workspace(session, "Same")
    session.add(Workspace(name="Same"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_unique_user_email(session: AsyncSession) -> None:
    session.add_all([User(email="a@x.com", name="A"), User(email="a@x.com", name="B")])
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_dataset_name_unique_per_workspace_only(session: AsyncSession) -> None:
    w1 = await make_workspace(session, "W1")
    w2 = await make_workspace(session, "W2")
    await make_dataset(session, w1, "Sales")
    await make_dataset(session, w2, "Sales")  # same name, other workspace: fine
    session.add(Dataset(workspace_id=w1.id, name="Sales"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_foreign_keys_enforced(session: AsyncSession) -> None:
    import uuid

    session.add(Dataset(workspace_id=uuid.uuid4(), name="orphan"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_invalid_role_rejected(session: AsyncSession) -> None:
    ws = await make_workspace(session)
    user = User(email="a@x.com", name="A")
    session.add(user)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="root"))  # type: ignore[arg-type]
    with pytest.raises((StatementError, LookupError)):
        await session.flush()


async def test_empty_audit_action_rejected(session: AsyncSession) -> None:
    session.add(AuditLog(principal="p", action="", object_type="t"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_naive_datetime_rejected(session: AsyncSession) -> None:
    session.add(User(email="a@x.com", name="A", created_at=datetime(2026, 1, 1)))
    with pytest.raises((StatementError, ValueError)):
        await session.flush()


async def test_non_utc_datetime_normalised(session: AsyncSession) -> None:
    tz = timezone(timedelta(hours=3))
    session.add(
        User(email="a@x.com", name="A", created_at=datetime(2026, 1, 1, 12, tzinfo=tz))
    )
    await session.commit()
    session.expunge_all()
    got = (await session.execute(select(User))).scalar_one()
    assert got.created_at == datetime(2026, 1, 1, 9, tzinfo=UTC)
    assert got.created_at.utcoffset() == timedelta(0)


# -- cascades ----------------------------------------------------------------


async def test_workspace_delete_cascades(session: AsyncSession) -> None:
    ws = await make_workspace(session)
    ds = await make_dataset(session, ws)
    user = User(email="a@x.com", name="A")
    session.add(user)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=Role.ADMIN))
    session.add(Report(workspace_id=ws.id, dataset_id=ds.id, name="R"))
    await session.commit()

    await session.delete(ws)
    await session.commit()

    assert await count(session, Dataset) == 0
    assert await count(session, Report) == 0
    assert await count(session, WorkspaceMember) == 0
    assert await count(session, User) == 1  # users outlive workspaces


async def test_user_delete_removes_memberships(session: AsyncSession) -> None:
    ws = await make_workspace(session)
    user = User(email="a@x.com", name="A")
    session.add(user)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER))
    await session.commit()

    await session.delete(user)
    await session.commit()
    assert await count(session, WorkspaceMember) == 0
    assert await count(session, Workspace) == 1


async def test_dataset_with_reports_cannot_be_deleted(session: AsyncSession) -> None:
    ws = await make_workspace(session)
    ds = await make_dataset(session, ws)
    session.add(Report(workspace_id=ws.id, dataset_id=ds.id, name="R"))
    await session.commit()

    await session.delete(ds)
    with pytest.raises(IntegrityError):
        await session.commit()


# -- session helpers ---------------------------------------------------------


async def test_session_scope_commits(factory: async_sessionmaker[AsyncSession]) -> None:
    gen = session_scope(factory)
    s = await anext(gen)
    s.add(Workspace(name="committed"))
    with pytest.raises(StopAsyncIteration):
        await anext(gen)
    async with factory() as check:
        assert await count(check, Workspace) == 1


async def test_session_scope_rolls_back(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    gen = session_scope(factory)
    s = await anext(gen)
    s.add(Workspace(name="discarded"))
    await s.flush()
    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("boom"))
    async with factory() as check:
        assert await count(check, Workspace) == 0


async def test_check_connection_ok(engine: AsyncEngine) -> None:
    await check_connection(engine)


async def test_check_connection_fails(tmp_path: Path) -> None:
    eng = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'missing' / 'x.db'}")
    with pytest.raises(Exception):  # noqa: B017 - driver-specific error type
        await check_connection(eng)
    await eng.dispose()
