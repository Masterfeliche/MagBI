"""Run a semantic query against a dataset's imported DuckDB file."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from magbi.api.datasets import get_dataset_or_404
from magbi.api.deps import ServicesDep, SessionDep
from magbi.api.errors import ApiError
from magbi.engine.cache import RedisQueryCache, run_cached
from magbi.engine.errors import QueryError
from magbi.engine.semantic import parse_query
from magbi.model.schema import DatasetDefinition
from magbi.services import Services

router = APIRouter(tags=["query"])


class QueryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: dict[str, Any]
    roles: list[str] = Field(default_factory=list)


@router.post("/workspaces/{wid}/datasets/{did}/query")
async def run_dataset_query(
    wid: uuid.UUID,
    did: uuid.UUID,
    body: QueryIn,
    session: SessionDep,
    svc: ServicesDep,
) -> dict[str, Any]:
    dataset = await get_dataset_or_404(session, wid, did)
    if dataset.definition is None:
        raise ApiError(422, "NO_DEFINITION", "dataset has no definition")
    model = DatasetDefinition.model_validate(dataset.definition)
    try:
        query = parse_query(body.query)
    except QueryError as exc:
        raise ApiError(422, exc.code, exc.message) from None
    if not svc.store.exists(str(dataset.id)):
        raise ApiError(409, "DATA_NOT_READY", "dataset has no imported data")
    con = svc.store.open_live(str(dataset.id))
    try:
        return run_cached(
            model,
            query,
            con,
            cache=_cache(svc),
            dataset_id=str(dataset.id),
            version=dataset.current_version,
            roles=tuple(body.roles),
        )
    except QueryError as exc:
        raise ApiError(422, exc.code, exc.message) from None
    finally:
        con.close()


def _cache(svc: Services) -> RedisQueryCache | None:
    if svc.settings.environment == "test":
        return None
    try:
        import redis
    except ImportError:
        return None
    client = redis.Redis.from_url(
        svc.settings.redis_url,
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
    )
    return RedisQueryCache(client)
