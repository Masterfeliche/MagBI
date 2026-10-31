"""Export to PDF, email subscriptions, data alerts and in-app notifications.

Each person manages their own subscriptions and alerts, on reports they can
see (as a workspace member, through a share, or through an app).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from magbi.api.deps import ActorDep, ServicesDep, SessionDep
from magbi.api.errors import ApiError
from magbi.auth.roles import Actor
from magbi.metadata.models import (
    Alert,
    AuditLog,
    Notification,
    Report,
    Subscription,
    utcnow,
)
from magbi.notify.alerts import CONDITIONS, alert_out, can_view, visual_value
from magbi.notify.pdf import ExportError
from magbi.notify.subscriptions import export_report, pdf_name, send_subscription
from magbi.refresh.schedule import validate_cron

router = APIRouter(tags=["sharing"])
workspace_router = APIRouter(tags=["sharing"])


def _me(actor: Actor) -> uuid.UUID:
    if actor.kind != "user":
        raise ApiError(
            403,
            "FORBIDDEN",
            "only a signed-in person has subscriptions, alerts and notifications",
        )
    return uuid.UUID(actor.subject)


async def _viewable(session: SessionDep, actor: Actor, report_id: uuid.UUID) -> Report:
    report = await session.get(Report, report_id)
    if report is None or not await can_view(session, actor, report):
        raise ApiError(404, "REPORT_NOT_FOUND", "report not found")
    return report


# ---------------------------------------------------------------- export


@workspace_router.get("/workspaces/{wid}/reports/{rid}/export.pdf")
async def export_pdf(
    wid: uuid.UUID,
    rid: uuid.UUID,
    session: SessionDep,
    svc: ServicesDep,
    actor: ActorDep,
) -> Response:
    """The published report as a PDF, one page per report page, as the caller sees it."""
    _me(actor)
    report = await session.get(Report, rid)
    if report is None or report.workspace_id != wid:
        raise ApiError(404, "REPORT_NOT_FOUND", "report not found")
    try:
        pdf = await export_report(svc, report, actor)
    except ExportError as exc:
        raise ApiError(503, "EXPORT_FAILED", str(exc)) from None
    session.add(
        AuditLog(
            principal=actor.email,
            action="report_export",
            object_type="report",
            object_id=str(rid),
            detail={"format": "pdf", "bytes": len(pdf)},
        )
    )
    await session.commit()
    name = pdf_name(report)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ---------------------------------------------------------------- subscriptions


class SubscriptionIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    report_id: uuid.UUID = Field(alias="reportId")
    cron: str = Field(min_length=9, max_length=100)
    is_active: bool = Field(default=True, alias="isActive")


def _subscription_out(item: Subscription, report: Report | None) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "reportId": str(item.report_id),
        "reportName": report.name if report else None,
        "workspaceId": str(report.workspace_id) if report else None,
        "cron": item.cron,
        "isActive": item.is_active,
        "lastSentAt": item.last_sent_at.isoformat() if item.last_sent_at else None,
        "lastError": item.last_error,
    }


def _cron(text: str) -> str:
    try:
        return validate_cron(text)
    except ValueError as exc:
        raise ApiError(422, "INVALID_SCHEDULE", str(exc)) from None


@router.get("/me/subscriptions")
async def my_subscriptions(
    session: SessionDep, actor: ActorDep, svc: ServicesDep
) -> dict[str, Any]:
    me = _me(actor)
    rows = await session.execute(
        select(Subscription, Report)
        .join(Report, Report.id == Subscription.report_id)
        .where(Subscription.user_id == me)
        .order_by(Report.name)
    )
    return {
        "mailReady": svc.mailer is not None,
        "items": [_subscription_out(item, report) for item, report in rows.all()],
    }


@router.post("/me/subscriptions", status_code=201)
async def subscribe(
    body: SubscriptionIn, session: SessionDep, actor: ActorDep, svc: ServicesDep
) -> dict[str, Any]:
    me = _me(actor)
    if svc.mailer is None:
        raise ApiError(
            409,
            "MAIL_NOT_CONFIGURED",
            "mail isn't set up on this server yet; ask an admin to set MAGBI_SMTP_HOST",
        )
    report = await _viewable(session, actor, body.report_id)
    item = Subscription(
        report_id=report.id, user_id=me, cron=_cron(body.cron), is_active=body.is_active
    )
    session.add(item)
    await session.commit()
    return _subscription_out(item, report)


async def _my_subscription(
    session: SessionDep, actor: Actor, subscription_id: uuid.UUID
) -> Subscription:
    item = await session.get(Subscription, subscription_id)
    if item is None or item.user_id != _me(actor):
        raise ApiError(404, "SUBSCRIPTION_NOT_FOUND", "subscription not found")
    return item


@router.put("/me/subscriptions/{subscription_id}")
async def update_subscription(
    subscription_id: uuid.UUID,
    body: SubscriptionIn,
    session: SessionDep,
    actor: ActorDep,
) -> dict[str, Any]:
    item = await _my_subscription(session, actor, subscription_id)
    report = await _viewable(session, actor, body.report_id)
    item.report_id, item.cron, item.is_active = (
        report.id,
        _cron(body.cron),
        body.is_active,
    )
    await session.commit()
    return _subscription_out(item, report)


@router.delete("/me/subscriptions/{subscription_id}", status_code=204)
async def unsubscribe(
    subscription_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> Response:
    await session.delete(await _my_subscription(session, actor, subscription_id))
    await session.commit()
    return Response(status_code=204)


@router.post("/me/subscriptions/{subscription_id}/send")
async def send_now(
    subscription_id: uuid.UUID, session: SessionDep, actor: ActorDep, svc: ServicesDep
) -> dict[str, Any]:
    """Send it now, to check how it looks."""
    item = await _my_subscription(session, actor, subscription_id)
    try:
        await send_subscription(svc, session, item, utcnow())
    except ExportError as exc:
        await session.commit()
        raise ApiError(503, "SEND_FAILED", str(exc)) from None
    await session.commit()
    return _subscription_out(item, await session.get(Report, item.report_id))


# ---------------------------------------------------------------- alerts


class AlertIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    report_id: uuid.UUID = Field(alias="reportId")
    visual_id: str = Field(min_length=1, max_length=200, alias="visualId")
    condition: str = Field(pattern="^(gt|gte|lt|lte|eq|ne)$")
    threshold: float
    is_active: bool = Field(default=True, alias="isActive")


async def _check_visual(
    svc: ServicesDep, session: SessionDep, actor: Actor, report: Report, visual_id: str
) -> float | None:
    """The visual's value now; refuses a visual an alert can't watch."""
    try:
        return await visual_value(svc, session, report, visual_id, actor)
    except ValueError as exc:
        raise ApiError(422, "ALERT_NOT_POSSIBLE", str(exc)) from None


@router.get("/me/alerts")
async def my_alerts(session: SessionDep, actor: ActorDep) -> list[dict[str, Any]]:
    me = _me(actor)
    rows = await session.execute(
        select(Alert, Report)
        .join(Report, Report.id == Alert.report_id)
        .where(Alert.user_id == me)
        .order_by(Alert.created_at)
    )
    return [alert_out(alert, report) for alert, report in rows.all()]


@router.post("/me/alerts", status_code=201)
async def create_alert(
    body: AlertIn, session: SessionDep, actor: ActorDep, svc: ServicesDep
) -> dict[str, Any]:
    me = _me(actor)
    report = await _viewable(session, actor, body.report_id)
    value = await _check_visual(svc, session, actor, report, body.visual_id)
    # The first check after a refresh fires if the condition holds then.
    alert = Alert(
        report_id=report.id,
        visual_id=body.visual_id,
        user_id=me,
        condition=body.condition,
        threshold=body.threshold,
        is_active=body.is_active,
        last_value=value,
        last_met=False,
    )
    session.add(alert)
    await session.commit()
    return alert_out(alert, report)


async def _my_alert(session: SessionDep, actor: Actor, alert_id: uuid.UUID) -> Alert:
    alert = await session.get(Alert, alert_id)
    if alert is None or alert.user_id != _me(actor):
        raise ApiError(404, "ALERT_NOT_FOUND", "alert not found")
    return alert


@router.put("/me/alerts/{alert_id}")
async def update_alert(
    alert_id: uuid.UUID,
    body: AlertIn,
    session: SessionDep,
    actor: ActorDep,
    svc: ServicesDep,
) -> dict[str, Any]:
    alert = await _my_alert(session, actor, alert_id)
    report = await _viewable(session, actor, body.report_id)
    if (body.report_id, body.visual_id) != (alert.report_id, alert.visual_id):
        alert.last_value = await _check_visual(
            svc, session, actor, report, body.visual_id
        )
    changed = (body.condition, body.threshold) != (alert.condition, alert.threshold)
    alert.report_id, alert.visual_id = report.id, body.visual_id
    alert.condition, alert.threshold, alert.is_active = (
        body.condition,
        body.threshold,
        body.is_active,
    )
    if changed:
        alert.last_met = False
    await session.commit()
    return alert_out(alert, report)


@router.delete("/me/alerts/{alert_id}", status_code=204)
async def delete_alert(
    alert_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> Response:
    await session.delete(await _my_alert(session, actor, alert_id))
    await session.commit()
    return Response(status_code=204)


@router.get("/alerts/conditions")
async def alert_conditions() -> list[dict[str, str]]:
    return [{"id": key, "label": label} for key, (label, _) in CONDITIONS.items()]


# ---------------------------------------------------------------- notifications


class ReadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] | None = None


@router.get("/me/notifications")
async def my_notifications(session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    me = _me(actor)
    items = await session.scalars(
        select(Notification)
        .where(Notification.user_id == me)
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    unread = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == me, Notification.read_at.is_(None))
    )
    return {
        "unread": int(unread or 0),
        "items": [
            {
                "id": str(n.id),
                "kind": n.kind,
                "title": n.title,
                "body": n.body,
                "link": n.link,
                "createdAt": n.created_at.isoformat(),
                "read": n.read_at is not None,
            }
            for n in items
        ],
    }


@router.post("/me/notifications/read", status_code=204)
async def mark_read(body: ReadIn, session: SessionDep, actor: ActorDep) -> Response:
    """Mark the given notifications read, or all of them when no ids are given."""
    me = _me(actor)
    query = update(Notification).where(
        Notification.user_id == me, Notification.read_at.is_(None)
    )
    if body.ids is not None:
        query = query.where(Notification.id.in_(body.ids))
    await session.execute(query.values(read_at=utcnow()))
    await session.commit()
    return Response(status_code=204)
