import duckdb
import pytest

from magbi.metadata.models import Dataset, RefreshStatus
from magbi.refresh.orchestrator import run_refresh
from tests.test_refresh.test_orchestrator import Env, fake, live_rows


@pytest.fixture
async def env(tmp_path):
    built = Env(tmp_path, fake(rows=3))
    await built.setup()
    yield built
    await built.engine.dispose()


def _with_column(definition: dict, expression: str) -> dict:
    raw = dict(definition)
    tables = [dict(table) for table in raw["tables"]]
    tables[0]["columns"] = [{"name": "id", "data_type": "integer"}]
    tables[0]["calculated_columns"] = [
        {"name": "Twice", "expression": expression, "data_type": "integer"}
    ]
    raw["tables"] = tables
    return raw


async def test_a_scalar_calculated_column_lands_in_the_live_file(env: Env) -> None:
    async with env.sessions() as session:
        dataset = await session.get(Dataset, env.dataset_id)
        assert dataset is not None and dataset.definition is not None
        dataset.definition = _with_column(dataset.definition, "orders[id] * 2")
        await session.commit()
    await run_refresh(env.deps, await env.queue())
    con = duckdb.connect(str(env.store.live_path(str(env.dataset_id))), read_only=True)
    assert con.execute('SELECT "Twice" FROM "orders" WHERE "id" = 1').fetchone() == (2,)
    con.close()


async def test_a_bad_calculated_column_keeps_the_previous_live_file(env: Env) -> None:
    await run_refresh(env.deps, await env.queue())
    assert live_rows(env) == 3
    async with env.sessions() as session:
        dataset = await session.get(Dataset, env.dataset_id)
        assert dataset is not None and dataset.definition is not None
        dataset.definition = _with_column(dataset.definition, "SUM(orders[id])")
        await session.commit()
    failed = await env.queue()
    await run_refresh(env.deps, failed)
    row = await env.refresh(failed)
    assert row.status is RefreshStatus.FAILED
    assert await env.current_version() == 1
    assert live_rows(env) == 3
