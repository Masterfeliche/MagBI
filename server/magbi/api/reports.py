"""Store a report: the published definition viewers see, and an editor's draft.

Editing saves a draft (``draft``). Publishing sends ``definition``, which
replaces what viewers and embeds see and clears the draft. Only editors and
admins are ever sent the draft.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from magbi.api.datasets import get_dataset_or_404
from magbi.api.deps import ActorDep, ServicesDep, SessionDep
from magbi.api.errors import ApiError
from magbi.api.workspaces import get_workspace_or_404
from magbi.auth.roles import Actor, role_of
from magbi.metadata.models import DatasetRefresh, RefreshStatus, Report, utcnow
from magbi.services import Services

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
    draft: dict[str, Any] | None = None
    discard_draft: bool = False


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
    last_refreshed_at: dt.datetime | None = None
    has_draft: bool = False
    draft: dict[str, Any] | None = None
    draft_updated_at: dt.datetime | None = None


def _out(report: Report, last_refreshed_at: dt.datetime | None = None, *, editor: bool = False) -> ReportOut:
    return ReportOut(
        id=report.id,
        workspace_id=report.workspace_id,
        dataset_id=report.dataset_id,
        name=report.name,
        definition=report.definition,
        is_published=report.is_published,
        created_at=report.created_at,
        updated_at=report.updated_at,
        last_refreshed_at=last_refreshed_at,
        has_draft=report.draft_definition is not None,
        draft=report.draft_definition if editor else None,
        draft_updated_at=report.draft_updated_at if editor else None,
    )


def _editor(actor: Actor, wid: uuid.UUID) -> bool:
    return role_of(actor, str(wid)) in ("editor", "admin")


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


@router.get("/workspaces/{wid}/reports", response_model=list[ReportOut])
async def list_reports(wid: uuid.UUID, session: SessionDep, actor: ActorDep) -> list[ReportOut]:
    await get_workspace_or_404(session, wid)
    rows = await session.execute(select(Report).where(Report.workspace_id == wid))
    editor = _editor(actor, wid)
    return [_out(report, editor=editor) for report in rows.scalars()]


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


@router.get("/workspaces/{wid}/reports/{rid}", response_model=ReportOut)
async def get_report(
    wid: uuid.UUID, rid: uuid.UUID, session: SessionDep, actor: ActorDep, svc: ServicesDep
) -> ReportOut:
    report = await _get(session, wid, rid)
    if actor.kind == "embed":
        if str(wid) != actor.workspace_id or str(rid) not in actor.reports:
            raise ApiError(
                403, "FORBIDDEN", "this embed token cannot read this report"
            )
        if not report.is_published:
            raise ApiError(
                403, "FORBIDDEN", "unpublished reports cannot be embedded"
            )
    last = await _last_refreshed(session, report.dataset_id)
    return _out(report, last or _data_changed(svc, report.dataset_id), editor=_editor(actor, wid))


def _data_changed(svc: Services, dataset_id: uuid.UUID) -> dt.datetime | None:
    """When the dataset's data file last changed: covers uploads, which have no refresh."""
    live = svc.store.live_path(str(dataset_id))
    if not live.is_file():
        return None
    return dt.datetime.fromtimestamp(live.stat().st_mtime, tz=dt.UTC)


async def _last_refreshed(
    session: AsyncSession, dataset_id: uuid.UUID
) -> dt.datetime | None:
    return await session.scalar(
        select(DatasetRefresh.finished_at)
        .where(
            DatasetRefresh.dataset_id == dataset_id,
            DatasetRefresh.status == RefreshStatus.SUCCEEDED,
            DatasetRefresh.finished_at.is_not(None),
        )
        .order_by(DatasetRefresh.finished_at.desc())
        .limit(1)
    )


@router.put("/workspaces/{wid}/reports/{rid}", response_model=ReportOut)
async def update_report(
    wid: uuid.UUID, rid: uuid.UUID, body: ReportUpdate, session: SessionDep, actor: ActorDep
) -> ReportOut:
    if body.definition is not None and body.draft is not None:
        raise ApiError(422, "DRAFT_AND_DEFINITION", "send a draft to save, or a definition to publish, not both")
    report = await _get(session, wid, rid)
    if body.name is not None:
        report.name = body.name.strip()
    if body.draft is not None:
        # A draft leaves what viewers see, and the report's updated time, alone.
        await session.execute(
            update(Report)
            .where(Report.id == report.id)
            .values(draft_definition=body.draft, draft_updated_at=utcnow(), updated_at=Report.updated_at)
        )
        await _commit(session)
        await session.refresh(report)
        return _out(report, editor=True)
    if body.definition is not None:
        report.definition = body.definition
        report.draft_definition = None
        report.draft_updated_at = None
    if body.discard_draft:
        report.draft_definition = None
        report.draft_updated_at = None
    if body.is_published is not None:
        report.is_published = body.is_published
    report.updated_at = utcnow()
    await _commit(session)
    await session.refresh(report)
    return _out(report, editor=_editor(actor, wid))
