"""Email subscriptions: a report sent as a PDF on a schedule, and the scheduler that runs them.

The scheduler also runs scheduled dataset refreshes (and the alert checks that
follow them), which before this only queued when something called
``enqueue_due``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magbi.auth.roles import Actor
from magbi.auth.tokens import issue_token, user_claims
from magbi.metadata.models import Report, Subscription, User, utcnow
from magbi.notify.alerts import actor_for_user, can_view, refresh_and_check
from magbi.notify.mail import Attachment
from magbi.notify.pdf import ExportError, report_pdf
from magbi.refresh.schedule import enqueue_due, previous_fire
from magbi.services import Services

log = logging.getLogger("magbi.scheduler")
EXPORT_TOKEN_MINUTES = 10


def export_token(svc: Services, actor: Actor) -> str:
    """A short-lived sign-in for the browser that prints the PDF, as this person."""
    cfg = svc.settings
    claims = user_claims(
        actor.subject,
        actor.email,
        actor.name,
        [{"id": wid, "role": role} for wid, role in actor.memberships],
        ttl_minutes=EXPORT_TOKEN_MINUTES,
        platform_admin=actor.platform_admin,
    )
    algorithm = "RS256" if cfg.jwt_private_key_pem else "HS256"
    return issue_token(
        claims,
        secret=cfg.jwt_secret,
        algorithm=algorithm,
        private_key=cfg.jwt_private_key_pem or None,
    )


async def export_report(svc: Services, report: Report, actor: Actor) -> bytes:
    pages = len((report.definition or {}).get("pages") or []) or 1
    return await report_pdf(
        svc.settings,
        export_token(svc, actor),
        str(report.workspace_id),
        str(report.id),
        pages,
    )


def pdf_name(report: Report, when: datetime | None = None) -> str:
    safe = (
        "".join(
            ch if ch.isalnum() or ch in " -_" else "_" for ch in report.name
        ).strip()
        or "report"
    )
    return f"{safe} {(when or datetime.now(UTC)).strftime('%Y-%m-%d')}.pdf"


async def send_subscription(
    svc: Services, session: AsyncSession, subscription: Subscription, now: datetime
) -> None:
    """Send one subscription now; records the outcome on it. Raises ``ExportError`` with the reason."""
    report = await session.get(Report, subscription.report_id)
    user = await session.get(User, subscription.user_id)
    try:
        if report is None or user is None or not user.is_active:
            raise ExportError("the report or its subscriber no longer exists")
        if svc.mailer is None:
            raise ExportError(
                "mail isn't set up on this server; ask an admin to set MAGBI_SMTP_HOST"
            )
        actor = await actor_for_user(session, user)
        if not await can_view(session, actor, report):
            raise ExportError("you can no longer see this report")
        pdf = await export_report(svc, report, actor)
        link = f"{svc.settings.web_base_url.rstrip('/')}/workspaces/{report.workspace_id}/reports/{report.id}/view"
        await svc.mailer.send(
            user.email,
            f"{report.name}: your MagBI subscription",
            f"The latest {report.name} is attached as a PDF.\n\nOpen it in MagBI: {link}\n",
            [Attachment(pdf_name(report, now), pdf)],
        )
    except ExportError as exc:
        subscription.last_error = str(exc)
        raise
    except Exception as exc:  # noqa: BLE001 - mail servers fail in many ways; keep the reason
        subscription.last_error = f"sending failed ({type(exc).__name__})"
        raise ExportError(subscription.last_error) from None
    finally:
        subscription.last_sent_at = now
    subscription.last_error = None


async def send_due_subscriptions(svc: Services, now: datetime) -> int:
    """Send each active subscription whose schedule has fired since it last went out."""
    if svc.mailer is None:
        return 0
    sent = 0
    async with svc.sessions() as session:
        subscriptions = (
            await session.scalars(
                select(Subscription).where(Subscription.is_active.is_(True))
            )
        ).all()
        for subscription in subscriptions:
            try:
                fired = previous_fire(subscription.cron, now)
            except ValueError:
                continue
            since = subscription.last_sent_at or subscription.created_at
            if since is not None and since >= fired:
                continue
            try:
                await send_subscription(svc, session, subscription, now)
                sent += 1
            except ExportError as exc:
                log.warning("subscription %s not sent: %s", subscription.id, exc)
            await session.commit()
    return sent


async def tick(svc: Services, now: datetime | None = None) -> None:
    """One pass: queue and run due refreshes (alerts follow each), then send due subscriptions."""
    moment = now or utcnow()
    queued: list[uuid.UUID] = await enqueue_due(svc.refresh, moment)
    for refresh_id in queued:
        await refresh_and_check(svc, refresh_id)
    await send_due_subscriptions(svc, moment)


async def run_scheduler(svc: Services, interval: float) -> None:
    """Run ``tick`` every ``interval`` seconds until cancelled, starting one interval after startup."""
    while True:
        await asyncio.sleep(interval)
        try:
            await tick(svc)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler pass failed")
