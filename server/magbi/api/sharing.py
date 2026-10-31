"""Share a report with people, and publish apps: sets of reports for an audience.

Neither needs workspace membership: a person a report is shared with, or who
is in a published app's audience, may view those reports and nothing else.
Changing shares and apps needs the workspace editor role.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select

from magbi.api.deps import ActorDep, SessionDep
from magbi.api.errors import ApiError
from magbi.auth.roles import permits
from magbi.metadata.models import (
    App,
    AppAudience,
    AppReport,
    AuditLog,
    Report,
    ReportShare,
    User,
    Workspace,
)
from magbi.sharing import granted_reports

router = APIRouter(tags=["sharing"])
workspace_router = APIRouter(tags=["sharing"])


class ShareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)


class AppIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    report_ids: list[uuid.UUID] = Field(
        default_factory=list, alias="reportIds", max_length=100
    )
    audience: list[str] = Field(default_factory=list, max_length=5000)
    is_published: bool = Field(default=False, alias="isPublished")


async def _report(session: SessionDep, wid: uuid.UUID, rid: uuid.UUID) -> Report:
    report = await session.get(Report, rid)
    if report is None or report.workspace_id != wid:
        raise ApiError(404, "REPORT_NOT_FOUND", "report not found")
    return report


async def _users(session: SessionDep, emails: list[str]) -> list[User]:
    wanted = sorted({email.strip().lower() for email in emails if email.strip()})
    if not wanted:
        return []
    found = list(
        await session.scalars(
            select(User).where(
                func.lower(User.email).in_(wanted), User.is_active.is_(True)
            )
        )
    )
    missing = sorted(set(wanted) - {user.email.lower() for user in found})
    if missing:
        raise ApiError(
            404,
            "USER_NOT_FOUND",
            f"no MagBI user with {'these emails' if len(missing) > 1 else 'this email'}: {', '.join(missing)}. "
            "Ask a platform admin to add them first.",
            emails=missing,
        )
    return found


def _audit(
    session: SessionDep,
    actor: ActorDep,
    action: str,
    object_type: str,
    object_id: str,
    detail: dict[str, Any],
) -> None:
    session.add(
        AuditLog(
            principal=actor.email or actor.subject,
            action=action,
            object_type=object_type,
            object_id=object_id,
            detail=detail,
        )
    )


# ---------------------------------------------------------------- shares


@workspace_router.get("/workspaces/{wid}/reports/{rid}/shares")
async def list_shares(
    wid: uuid.UUID, rid: uuid.UUID, session: SessionDep
) -> list[dict[str, Any]]:
    await _report(session, wid, rid)
    rows = await session.execute(
        select(ReportShare, User)
        .join(User, User.id == ReportShare.user_id)
        .where(ReportShare.report_id == rid)
        .order_by(User.email)
    )
    return [
        {
            "userId": str(user.id),
            "email": user.email,
            "name": user.name,
            "sharedBy": share.shared_by,
            "createdAt": share.created_at.isoformat(),
        }
        for share, user in rows.all()
    ]


@workspace_router.post("/workspaces/{wid}/reports/{rid}/shares", status_code=201)
async def share_report(
    wid: uuid.UUID, rid: uuid.UUID, body: ShareIn, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    report = await _report(session, wid, rid)
    (user,) = await _users(session, [body.email])
    existing = await session.scalar(
        select(ReportShare).where(
            ReportShare.report_id == rid, ReportShare.user_id == user.id
        )
    )
    if existing is None:
        existing = ReportShare(
            report_id=rid, user_id=user.id, shared_by=actor.email or actor.subject
        )
        session.add(existing)
        _audit(
            session,
            actor,
            "report_share",
            "report",
            str(rid),
            {"with": user.email, "report": report.name},
        )
        await session.commit()
    return {
        "userId": str(user.id),
        "email": user.email,
        "name": user.name,
        "sharedBy": existing.shared_by,
    }


@workspace_router.delete(
    "/workspaces/{wid}/reports/{rid}/shares/{user_id}", status_code=204
)
async def unshare_report(
    wid: uuid.UUID,
    rid: uuid.UUID,
    user_id: uuid.UUID,
    session: SessionDep,
    actor: ActorDep,
) -> Response:
    await _report(session, wid, rid)
    gone = await session.execute(
        delete(ReportShare).where(
            ReportShare.report_id == rid, ReportShare.user_id == user_id
        )
    )
    if not getattr(gone, "rowcount", 0):
        raise ApiError(
            404, "SHARE_NOT_FOUND", "this report isn't shared with that person"
        )
    _audit(session, actor, "report_unshare", "report", str(rid), {"user": str(user_id)})
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- apps


async def _app_out(session: SessionDep, app: App) -> dict[str, Any]:
    reports = (
        await session.execute(
            select(Report.id, Report.name)
            .join(AppReport, AppReport.report_id == Report.id)
            .where(AppReport.app_id == app.id)
            .order_by(AppReport.position)
        )
    ).all()
    audience = await session.scalars(
        select(User.email)
        .join(AppAudience, AppAudience.user_id == User.id)
        .where(AppAudience.app_id == app.id)
        .order_by(User.email)
    )
    workspace = await session.get(Workspace, app.workspace_id)
    return {
        "id": str(app.id),
        "workspaceId": str(app.workspace_id),
        "workspaceName": workspace.name if workspace else "",
        "name": app.name,
        "description": app.description,
        "isPublished": app.is_published,
        "reports": [
            {"id": str(report_id), "name": name} for report_id, name in reports
        ],
        "audience": list(audience),
        "updatedBy": app.updated_by,
        "updatedAt": app.updated_at.isoformat() if app.updated_at else None,
    }


async def _save_app(
    session: SessionDep, actor: ActorDep, wid: uuid.UUID, app: App, body: AppIn
) -> App:
    reports = list(dict.fromkeys(body.report_ids))
    if reports:
        found = set(
            await session.scalars(
                select(Report.id).where(
                    Report.id.in_(reports), Report.workspace_id == wid
                )
            )
        )
        missing = [str(item) for item in reports if item not in found]
        if missing:
            raise ApiError(
                404,
                "REPORT_NOT_FOUND",
                f"these reports aren't in this workspace: {', '.join(missing)}",
            )
    users = await _users(session, body.audience)
    app.name = body.name.strip()
    app.description = body.description
    app.is_published = body.is_published
    app.updated_by = actor.email or actor.subject
    session.add(app)
    await session.flush()
    await session.execute(delete(AppReport).where(AppReport.app_id == app.id))
    await session.execute(delete(AppAudience).where(AppAudience.app_id == app.id))
    session.add_all(
        AppReport(app_id=app.id, report_id=report_id, position=index)
        for index, report_id in enumerate(reports)
    )
    session.add_all(AppAudience(app_id=app.id, user_id=user.id) for user in users)
    _audit(
        session,
        actor,
        "app_save",
        "app",
        str(app.id),
        {
            "name": app.name,
            "published": app.is_published,
            "reports": len(reports),
            "audience": len(users),
        },
    )
    await session.commit()
    await session.refresh(app)
    return app


@workspace_router.get("/workspaces/{wid}/apps")
async def list_workspace_apps(
    wid: uuid.UUID, session: SessionDep
) -> list[dict[str, Any]]:
    apps = await session.scalars(
        select(App).where(App.workspace_id == wid).order_by(App.name)
    )
    return [await _app_out(session, app) for app in apps]


@workspace_router.post("/workspaces/{wid}/apps", status_code=201)
async def create_app(
    wid: uuid.UUID, body: AppIn, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    return await _app_out(
        session, await _save_app(session, actor, wid, App(workspace_id=wid), body)
    )


async def _workspace_app(session: SessionDep, wid: uuid.UUID, app_id: uuid.UUID) -> App:
    app = await session.get(App, app_id)
    if app is None or app.workspace_id != wid:
        raise ApiError(404, "APP_NOT_FOUND", "app not found")
    return app


@workspace_router.put("/workspaces/{wid}/apps/{app_id}")
async def update_app(
    wid: uuid.UUID, app_id: uuid.UUID, body: AppIn, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    return await _app_out(
        session,
        await _save_app(
            session, actor, wid, await _workspace_app(session, wid, app_id), body
        ),
    )


@workspace_router.delete("/workspaces/{wid}/apps/{app_id}", status_code=204)
async def delete_app(
    wid: uuid.UUID, app_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> Response:
    app = await _workspace_app(session, wid, app_id)
    _audit(session, actor, "app_delete", "app", str(app.id), {"name": app.name})
    await session.delete(app)
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- what I can see


@router.get("/me/shared")
async def shared_with_me(session: SessionDep, actor: ActorDep) -> list[dict[str, Any]]:
    """Reports shared with me directly (apps are listed separately)."""
    if actor.kind != "user":
        return []
    rows = await session.execute(
        select(ReportShare, Report, Workspace)
        .join(Report, Report.id == ReportShare.report_id)
        .join(Workspace, Workspace.id == Report.workspace_id)
        .where(ReportShare.user_id == uuid.UUID(actor.subject))
        .order_by(Report.name)
    )
    return [
        {
            "reportId": str(report.id),
            "reportName": report.name,
            "workspaceId": str(workspace.id),
            "workspaceName": workspace.name,
            "sharedBy": share.shared_by,
            "sharedAt": share.created_at.isoformat(),
        }
        for share, report, workspace in rows.all()
    ]


@router.get("/me/apps")
async def my_apps(session: SessionDep, actor: ActorDep) -> list[dict[str, Any]]:
    """Published apps whose audience includes me."""
    if actor.kind != "user":
        return []
    apps = await session.scalars(
        select(App)
        .join(AppAudience, AppAudience.app_id == App.id)
        .where(
            AppAudience.user_id == uuid.UUID(actor.subject), App.is_published.is_(True)
        )
        .order_by(App.name)
    )
    return [await _app_out(session, app) for app in apps]


@router.get("/apps/{app_id}")
async def get_app(
    app_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    """An app, for its audience (once published) or the workspace's members."""
    app = await session.get(App, app_id)
    if app is None:
        raise ApiError(404, "APP_NOT_FOUND", "app not found")
    member = permits(actor, str(app.workspace_id), "viewer")
    if not member:
        audience = actor.kind == "user" and await session.scalar(
            select(AppAudience.app_id).where(
                AppAudience.app_id == app.id,
                AppAudience.user_id == uuid.UUID(actor.subject),
            )
        )
        if not (audience and app.is_published):
            raise ApiError(404, "APP_NOT_FOUND", "app not found")
    out = await _app_out(session, app)
    if not member:
        # The audience sees the app's reports, not who else is in it.
        out["audience"] = []
        granted = await granted_reports(session, actor)
        out["reports"] = [
            item for item in out["reports"] if uuid.UUID(item["id"]) in granted
        ]
    return out
