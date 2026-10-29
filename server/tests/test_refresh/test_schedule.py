from datetime import UTC, datetime

import pytest

from magbi.metadata.models import Dataset, DatasetRefresh, RefreshStatus
from magbi.refresh.schedule import enqueue_due
from tests.test_refresh.test_orchestrator import Env, fake


@pytest.fixture
async def env(tmp_path):
    built = Env(tmp_path, fake())
    await built.setup()
    yield built
    await built.engine.dispose()


async def test_a_due_dataset_is_queued_once_per_fire(env: Env) -> None:
    now = datetime(2026, 10, 29, 12, 5, tzinfo=UTC)
    async with env.sessions() as session:
        dataset = await session.get(Dataset, env.dataset_id)
        assert dataset is not None
        dataset.schedule_cron = "*/30 * * * *"
        await session.commit()
    first = await enqueue_due(env.deps, now)
    assert len(first) == 1
    async with env.sessions() as session:
        row = await session.get(DatasetRefresh, first[0])
        assert row is not None and row.trigger == "schedule"
    assert await enqueue_due(env.deps, now) == []
    async with env.sessions() as session:
        row = await session.get(DatasetRefresh, first[0])
        assert row is not None
        row.status = RefreshStatus.SUCCEEDED
        row.finished_at = now
        await session.commit()
    assert await enqueue_due(env.deps, now) == []
