"""Dataset refresh endpoints: trigger, status, history.

``POST`` queues a refresh and returns 202 immediately; the work runs after the
response (FastAPI background task now, a Celery task in Sprint 8). Poll the status
endpoint for ``queued`` -> ``running`` -> ``succeeded`` | ``failed``.
Cancelling a running refresh is not implemented yet.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from magbi.api.datasets import get_dataset_or_404
from magbi.api.deps import ServicesDep, SessionDep
from magbi.api.errors import ApiError
from magbi.api.schemas import RefreshOut
from magbi.metadata.models import DatasetRefresh
from magbi.refresh.orchestrator import queue_refresh, run_refresh
from magbi.refresh.schedule import validate_cron

router = APIRouter(tags=["refresh"])


class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cron: str = Field(min_length=1, max_length=100)


def _out(r: DatasetRefresh) -> RefreshOut:
    return RefreshOut(
        id=r.id,
        dataset_id=r.dataset_id,
        status=r.status.value,
        trigger=r.trigger,
        version=r.version,
        created_at=r.created_at,
        started_at=r.started_at,
        finished_at=r.finished_at,
        result=r.result,
        error=r.error,
    )


@router.put("/workspaces/{wid}/datasets/{did}/schedule")
async def set_schedule(
    wid: uuid.UUID, did: uuid.UUID, body: ScheduleIn, session: SessionDep
) -> dict[str, str]:
    dataset = await get_dataset_or_404(session, wid, did)
    try:
        cron = validate_cron(body.cron)
    except ValueError:
        raise ApiError(
            422, "BAD_SCHEDULE", "cron expression must have five fields"
        ) from None
    dataset.schedule_cron = cron
    await session.commit()
    return {"cron": dataset.schedule_cron}


@router.delete("/workspaces/{wid}/datasets/{did}/schedule", status_code=204)
async def clear_schedule(wid: uuid.UUID, did: uuid.UUID, session: SessionDep) -> None:
    dataset = await get_dataset_or_404(session, wid, did)
    dataset.schedule_cron = None
    await session.commit()


@router.post("/workspaces/{wid}/datasets/{did}/refresh", status_code=202)
async def trigger_refresh(
    wid: uuid.UUID,
    did: uuid.UUID,
    background: BackgroundTasks,
    svc: ServicesDep,
    session: SessionDep,
) -> dict[str, str]:
    dataset = await get_dataset_or_404(session, wid, did)
    if not dataset.definition:
        raise ApiError(
            422,
            "DATASET_NOT_CONFIGURED",
            "dataset has no definition; set the connection and tables first",
        )
    refresh = await queue_refresh(session, dataset.id)  # 409 if one is active
    background.add_task(run_refresh, svc.refresh, refresh.id)
    return {"refresh_id": str(refresh.id), "status": refresh.status.value}


@router.get(
    "/workspaces/{wid}/datasets/{did}/refresh/history", response_model=list[RefreshOut]
)
async def refresh_history(
    wid: uuid.UUID,
    did: uuid.UUID,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RefreshOut]:
    await get_dataset_or_404(session, wid, did)
    rows = await session.execute(
        select(DatasetRefresh)
        .where(DatasetRefresh.dataset_id == did)
        .order_by(DatasetRefresh.created_at.desc(), DatasetRefresh.id)
        .limit(limit)
    )
    return [_out(r) for r in rows.scalars()]


@router.get(
    "/workspaces/{wid}/datasets/{did}/refresh/{job_id}", response_model=RefreshOut
)
async def refresh_status(
    wid: uuid.UUID, did: uuid.UUID, job_id: uuid.UUID, session: SessionDep
) -> RefreshOut:
    await get_dataset_or_404(session, wid, did)
    refresh = await session.get(DatasetRefresh, job_id)
    if refresh is None or refresh.dataset_id != did:
        raise ApiError(404, "REFRESH_NOT_FOUND", "refresh not found")
    return _out(refresh)
