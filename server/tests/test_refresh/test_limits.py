import uuid

import pytest
from sqlalchemy import func, select

from magbi.metadata.models import Dataset, DatasetRefresh
from magbi.refresh.orchestrator import RefreshConflict, RefreshLimit, queue_refresh
from tests.test_refresh.test_orchestrator import Env, fake


@pytest.fixture
async def env(tmp_path):
    built = Env(tmp_path, fake())
    await built.setup()
    yield built
    await built.engine.dispose()


async def _extra(env: Env) -> uuid.UUID:
    async with env.sessions() as session:
        current = await session.get(Dataset, env.dataset_id)
        assert current is not None
        dataset = Dataset(workspace_id=current.workspace_id, name=str(uuid.uuid4()))
        session.add(dataset)
        await session.commit()
        return dataset.id


async def test_dataset_workspace_and_platform_caps(env: Env) -> None:
    async with env.sessions() as session:
        await queue_refresh(session, env.dataset_id)
    async with env.sessions() as session:
        with pytest.raises(RefreshConflict):
            await queue_refresh(session, env.dataset_id)
    others = [await _extra(env) for _ in range(3)]
    async with env.sessions() as session:
        await queue_refresh(session, others[0])
        await queue_refresh(session, others[1])
        with pytest.raises(RefreshLimit) as limited:
            await queue_refresh(session, others[2])
        assert limited.value.scope == "workspace"
    async with env.sessions() as session:
        count = await session.scalar(select(func.count()).select_from(DatasetRefresh))
    assert count == 3
    async with env.sessions() as session:
        with pytest.raises(RefreshLimit) as platform:
            await queue_refresh(session, others[2], platform_limit=3)
        assert platform.value.scope == "platform"
