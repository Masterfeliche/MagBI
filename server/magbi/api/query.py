"""Run a semantic query against a dataset's imported DuckDB file."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from magbi.api.datasets import get_dataset_or_404
from magbi.api.deps import ActorDep, ServicesDep, SessionDep
from magbi.api.errors import ApiError
from magbi.auth.roles import Actor, permits
from magbi.engine.cache import RedisQueryCache, run_cached
from magbi.engine.errors import QueryError
from magbi.engine.semantic import parse_query
from magbi.model.schema import DatasetDefinition
from magbi.services import Services
from magbi.sharing import dataset_granted

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
    actor: ActorDep,
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
            roles=query_roles(
                actor, body.roles, str(wid), str(dataset.id), model,
                granted=not permits(actor, str(wid), "viewer") and await dataset_granted(session, actor, wid, did),
            ),
            user=actor.email,
        )
    except QueryError as exc:
        raise ApiError(422, exc.code, exc.message) from None
    finally:
        con.close()


def query_roles(
    actor: Actor, requested: list[str], workspace_id: str, dataset_id: str, model: DatasetDefinition, granted: bool = False
) -> tuple[str, ...]:
    """The roles a query runs under.

    Embed tokens carry theirs. Editors see every row, or "view as" the roles they
    name. A viewer gets the roles they are a member of; when the dataset has roles
    and they are in none, they are refused, as in Power BI.
    """
    if actor.kind == "embed":
        if actor.workspace_id != workspace_id or dataset_id not in actor.datasets:
            raise ApiError(
                403, "FORBIDDEN", "this embed token cannot query this dataset"
            )
        return actor.rls_roles
    if actor.kind == "dev" or (
        actor.kind == "user" and permits(actor, workspace_id, "editor")
    ):
        return tuple(requested)
    # A report shared with them, or in their app, lets a person query its dataset as a viewer.
    if actor.kind == "user" and (permits(actor, workspace_id, "viewer") or granted):
        if requested:
            raise ApiError(403, "FORBIDDEN", "only an editor can set query roles")
        if not model.roles:
            return ()
        email = actor.email.strip().lower()
        mine = tuple(role.name for role in model.roles if email in role.members)
        if not mine:
            raise ApiError(
                403,
                "RLS_NO_ROLE",
                "this dataset limits rows by role and you are in none of its roles; ask its owner to add you",
            )
        return mine
    raise ApiError(403, "FORBIDDEN", "this token cannot query")


def _cache(svc: Services) -> RedisQueryCache | None:
    if svc.settings.environment in ("test", "dev"):
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
