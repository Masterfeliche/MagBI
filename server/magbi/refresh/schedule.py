"""Five-field cron schedules for dataset refresh."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import cast

from croniter import croniter
from sqlalchemy import select

from magbi.metadata.models import Dataset, DatasetRefresh, RefreshStatus
from magbi.refresh.orchestrator import RefreshConflict, RefreshDeps, queue_refresh


def validate_cron(expression: str) -> str:
    """Return a trimmed five-field cron, or raise ``ValueError``."""
    text = " ".join(expression.split())
    if len(text.split(" ")) != 5 or not croniter.is_valid(text):
        raise ValueError("cron expression must have five fields")
    return text


def previous_fire(expression: str, now: datetime) -> datetime:
    """The latest fire strictly before ``now``."""
    fired = cast(datetime, croniter(expression, now).get_prev(datetime))
    if fired.tzinfo is None and now.tzinfo is not None:
        return fired.replace(tzinfo=now.tzinfo)
    return fired


async def enqueue_due(deps: RefreshDeps, now: datetime) -> list[uuid.UUID]:
    """Queue one scheduled refresh for each dataset whose last fire is still due."""
    queued: list[uuid.UUID] = []
    async with deps.sessions() as session:
        datasets = (
            await session.scalars(
                select(Dataset).where(Dataset.schedule_cron.is_not(None))
            )
        ).all()
        for dataset in datasets:
            if dataset.schedule_cron is None:
                continue
            try:
                fired = previous_fire(dataset.schedule_cron, now)
            except ValueError:
                continue
            finished = await session.scalar(
                select(DatasetRefresh.finished_at)
                .where(
                    DatasetRefresh.dataset_id == dataset.id,
                    DatasetRefresh.status == RefreshStatus.SUCCEEDED,
                )
                .order_by(DatasetRefresh.finished_at.desc())
                .limit(1)
            )
            if finished is not None and finished >= fired:
                continue
            try:
                refresh = await queue_refresh(session, dataset.id, trigger="schedule")
            except RefreshConflict:
                continue
            queued.append(refresh.id)
    return queued
