"""Who may see a report besides workspace members: people it is shared with, and app audiences.

Grants are read from the database on every request, so a share or an app
takes effect at once, without signing in again.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magbi.auth.roles import Actor
from magbi.metadata.models import App, AppAudience, AppReport, Report, ReportShare


def _user_id(actor: Actor) -> uuid.UUID | None:
    if actor.kind != "user":
        return None
    try:
        return uuid.UUID(actor.subject)
    except ValueError:
        return None


async def granted_reports(session: AsyncSession, actor: Actor) -> set[uuid.UUID]:
    """Reports shared with the caller, plus the reports of published apps whose audience includes them."""
    user = _user_id(actor)
    if user is None:
        return set()
    shared = await session.scalars(
        select(ReportShare.report_id).where(ReportShare.user_id == user)
    )
    in_apps = await session.scalars(
        select(AppReport.report_id)
        .join(App, App.id == AppReport.app_id)
        .join(AppAudience, AppAudience.app_id == App.id)
        .where(AppAudience.user_id == user, App.is_published.is_(True))
    )
    return set(shared) | set(in_apps)


async def report_granted(
    session: AsyncSession, actor: Actor, workspace_id: uuid.UUID, report_id: uuid.UUID
) -> bool:
    report = await session.get(Report, report_id)
    return (
        report is not None
        and report.workspace_id == workspace_id
        and report_id in await granted_reports(session, actor)
    )


async def dataset_granted(
    session: AsyncSession, actor: Actor, workspace_id: uuid.UUID, dataset_id: uuid.UUID
) -> bool:
    """True when a report the caller may see reads this dataset."""
    granted = await granted_reports(session, actor)
    if not granted:
        return False
    found = await session.scalar(
        select(Report.id)
        .where(
            Report.id.in_(granted),
            Report.workspace_id == workspace_id,
            Report.dataset_id == dataset_id,
        )
        .limit(1)
    )
    return found is not None


async def workspace_granted(
    session: AsyncSession, actor: Actor, workspace_id: uuid.UUID
) -> bool:
    """True when the caller may see at least one report in this workspace."""
    granted = await granted_reports(session, actor)
    if not granted:
        return False
    found = await session.scalar(
        select(Report.id)
        .where(Report.id.in_(granted), Report.workspace_id == workspace_id)
        .limit(1)
    )
    return found is not None
