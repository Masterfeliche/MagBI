"""Store a report definition and its published flag."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from magbi.api.datasets import get_dataset_or_404
from magbi.api.deps import SessionDep
from magbi.api.errors import ApiError
from magbi.api.workspaces import get_workspace_or_404
from magbi.metadata.models import Report, utcnow

router = APIRouter(tags=["reports"])

Name = Field(min_length=1, max_length=200)


class ReportIn(BaseModel):
    name: str = Name
    dataset_id: uuid.UUID
    definition: dict[str, Any] = Field(default_factory=dict)
    is_published: bool = False


class ReportUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    definition: dict[str, Any] | None = None
    is_published: bool | None = None


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    dataset_id: uuid.UUID
    name: str
    definition: dict[str, Any]
    is_published: bool
    created_at: dt.datetime
    updated_at: dt.datetime


def _out(report: Report) -> ReportOut:
    return ReportOut(
        id=report.id,
        workspace_id=report.workspace_id,
        dataset_id=report.dataset_id,
        name=report.name,
        definition=report.definition,
        is_published=report.is_published,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ApiError(409, "REPORT_EXISTS", "a report with this name already exists") from None


async def _get(session: AsyncSession, wid: uuid.UUID, rid: uuid.UUID) -> Report:
    report = await session.get(Report, rid)
    if report is None or report.workspace_id != wid:
        raise ApiError(404, "REPORT_NOT_FOUND", "report not found")
    return report


@router.post("/workspaces/{wid}/reports", status_code=201, response_model=ReportOut)
async def create_report(wid: uuid.UUID, body: ReportIn, session: SessionDep) -> ReportOut:
    await get_workspace_or_404(session, wid)
    await get_dataset_or_404(session, wid, body.dataset_id)
    report = Report(
        workspace_id=wid,
        dataset_id=body.dataset_id,
        name=body.name.strip(),
        definition=body.definition,
        is_published=body.is_published,
    )
    session.add(report)
    await _commit(session)
    await session.refresh(report)
    return _out(report)


@router.put("/workspaces/{wid}/reports/{rid}", response_model=ReportOut)
async def update_report(
    wid: uuid.UUID, rid: uuid.UUID, body: ReportUpdate, session: SessionDep
) -> ReportOut:
    report = await _get(session, wid, rid)
    if body.name is not None:
        report.name = body.name.strip()
    if body.definition is not None:
        report.definition = body.definition
    if body.is_published is not None:
        report.is_published = body.is_published
    report.updated_at = utcnow()
    await _commit(session)
    await session.refresh(report)
    return _out(report)
