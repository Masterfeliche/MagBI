"""Data alerts, as in Power BI: tell a person when a card's value crosses a threshold.

Alerts are checked after each successful refresh of the report's dataset. The
value is read as the alert's owner would see it, row-level security included.
An alert fires when its condition becomes true, not again while it stays true.
"""

from __future__ import annotations

import logging
import operator
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magbi.auth.roles import Actor, permits
from magbi.metadata.models import (
    Alert,
    Dataset,
    DatasetRefresh,
    Notification,
    RefreshStatus,
    Report,
    User,
    WorkspaceMember,
    utcnow,
)
from magbi.model.schema import DatasetDefinition
from magbi.notify.visuals import find_visual, value_query, visual_title
from magbi.services import Services

log = logging.getLogger("magbi.alerts")

CONDITIONS: dict[str, tuple[str, Callable[[float, float], bool]]] = {
    "gt": ("above", operator.gt),
    "gte": ("at or above", operator.ge),
    "lt": ("below", operator.lt),
    "lte": ("at or below", operator.le),
    "eq": ("equal to", operator.eq),
    "ne": ("not equal to", operator.ne),
}


async def actor_for_user(session: AsyncSession, user: User) -> Actor:
    """The person as the API would see them, with their workspace roles as stored now."""
    rows = await session.execute(
        select(WorkspaceMember.workspace_id, WorkspaceMember.role).where(
            WorkspaceMember.user_id == user.id
        )
    )
    return Actor(
        "user",
        str(user.id),
        user.email,
        user.name,
        platform_admin=user.is_platform_admin,
        memberships=tuple(
            (str(wid), str(role.value if hasattr(role, "value") else role))
            for wid, role in rows.all()
        ),
    )


async def can_view(session: AsyncSession, actor: Actor, report: Report) -> bool:
    from magbi.sharing import report_granted

    return permits(actor, str(report.workspace_id), "viewer") or await report_granted(
        session, actor, report.workspace_id, report.id
    )


async def visual_value(
    svc: Services, session: AsyncSession, report: Report, visual_id: str, actor: Actor
) -> float | None:
    """The visual's value for this person. Raises ``ValueError`` with a reason when it can't be read."""
    from magbi.api.errors import ApiError
    from magbi.api.query import query_roles
    from magbi.engine.cache import run_cached
    from magbi.engine.errors import QueryError
    from magbi.engine.semantic import parse_query
    from magbi.sharing import dataset_granted

    dataset = await session.get(Dataset, report.dataset_id)
    if dataset is None or dataset.definition is None:
        raise ValueError("the report's dataset has no model")
    if not svc.store.exists(str(dataset.id)):
        raise ValueError("the report's dataset has no data yet")
    model = DatasetDefinition.model_validate(dataset.definition)
    wid = str(report.workspace_id)
    try:
        roles = query_roles(
            actor,
            [],
            wid,
            str(dataset.id),
            model,
            granted=not permits(actor, wid, "viewer")
            and await dataset_granted(session, actor, report.workspace_id, dataset.id),
        )
        query = parse_query(value_query(report.definition or {}, visual_id))
    except ApiError as exc:
        raise ValueError(exc.message) from None
    except QueryError as exc:
        raise ValueError(exc.message) from None
    con = svc.store.open_live(str(dataset.id))
    try:
        result = run_cached(
            model,
            query,
            con,
            cache=None,
            dataset_id=str(dataset.id),
            version=dataset.current_version,
            roles=roles,
            user=actor.email,
        )
    except QueryError as exc:
        raise ValueError(exc.message) from None
    finally:
        con.close()
    rows = result.get("rows") or []
    value = rows[0][0] if rows and rows[0] else None
    return None if value is None else float(value)


def _number(value: float) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


async def check_alerts(svc: Services, dataset_id: uuid.UUID) -> int:
    """Check every active alert on reports of this dataset; returns how many fired. Never raises."""
    fired = 0
    try:
        async with svc.sessions() as session:
            rows = (
                await session.execute(
                    select(Alert, Report, User)
                    .join(Report, Report.id == Alert.report_id)
                    .join(User, User.id == Alert.user_id)
                    .where(
                        Report.dataset_id == dataset_id,
                        Alert.is_active.is_(True),
                        User.is_active.is_(True),
                    )
                )
            ).all()
            for alert, report, user in rows:
                if await _check_one(svc, session, alert, report, user):
                    fired += 1
            await session.commit()
    except Exception:
        log.exception("alert check failed for dataset %s", dataset_id)
    return fired


async def _check_one(
    svc: Services, session: AsyncSession, alert: Alert, report: Report, user: User
) -> bool:
    actor = await actor_for_user(session, user)
    alert.last_checked_at = utcnow()
    if not await can_view(session, actor, report):
        return False
    try:
        value = await visual_value(svc, session, report, alert.visual_id, actor)
    except ValueError as exc:
        log.info("alert %s skipped: %s", alert.id, exc)
        return False
    label, test = CONDITIONS.get(alert.condition, CONDITIONS["gt"])
    met = value is not None and test(value, alert.threshold)
    was_met = alert.last_met
    alert.last_value = value
    alert.last_met = met
    if not met or was_met:
        return False
    alert.last_fired_at = utcnow()
    found = find_visual(report.definition or {}, alert.visual_id)
    title = visual_title(found[1]) if found else "A card"
    link = f"/workspaces/{report.workspace_id}/reports/{report.id}/view"
    text = f"{title} in {report.name} is {_number(value or 0)}, {label} your alert at {_number(alert.threshold)}."
    session.add(
        Notification(
            user_id=user.id,
            kind="alert",
            title=f"{title} is {label} {_number(alert.threshold)}",
            body=text,
            link=link,
        )
    )
    if svc.mailer is not None:
        try:
            url = svc.settings.web_base_url.rstrip("/") + link
            await svc.mailer.send(
                user.email,
                f"MagBI alert: {title} is {label} {_number(alert.threshold)}",
                f"{text}\n\nOpen the report: {url}\n",
            )
        except Exception as exc:  # noqa: BLE001 - the in-app notification still stands
            log.warning("alert mail to %s failed: %s", user.email, type(exc).__name__)
    return True


async def refresh_and_check(svc: Services, refresh_id: uuid.UUID) -> None:
    """Run a queued refresh, then check its dataset's alerts when it succeeded."""
    from magbi.refresh.orchestrator import run_refresh

    await run_refresh(svc.refresh, refresh_id)
    async with svc.sessions() as session:
        row = await session.get(DatasetRefresh, refresh_id)
        succeeded = row is not None and row.status == RefreshStatus.SUCCEEDED
        dataset_id = row.dataset_id if row is not None else None
    if succeeded and dataset_id is not None:
        await check_alerts(svc, dataset_id)


def alert_out(alert: Alert, report: Report | None = None) -> dict[str, Any]:
    found = (
        find_visual(report.definition or {}, alert.visual_id)
        if report is not None
        else None
    )
    return {
        "id": str(alert.id),
        "reportId": str(alert.report_id),
        "reportName": report.name if report is not None else None,
        "visualId": alert.visual_id,
        "visualTitle": visual_title(found[1]) if found else None,
        "condition": alert.condition,
        "threshold": alert.threshold,
        "isActive": alert.is_active,
        "lastValue": alert.last_value,
        "lastMet": alert.last_met,
        "lastCheckedAt": alert.last_checked_at.isoformat()
        if alert.last_checked_at
        else None,
        "lastFiredAt": alert.last_fired_at.isoformat() if alert.last_fired_at else None,
    }
