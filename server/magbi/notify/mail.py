"""Outgoing mail for subscriptions and alerts.

Mail is off until ``MAGBI_SMTP_HOST`` is set. Tests swap in a mailer that
keeps messages in memory.
"""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from magbi.config import Settings


@dataclass
class Attachment:
    filename: str
    content: bytes
    mime: str = "application/pdf"


class Mailer(Protocol):
    async def send(
        self,
        to: str,
        subject: str,
        body: str,
        attachments: list[Attachment] | None = None,
    ) -> None: ...


@dataclass
class SmtpMailer:
    host: str
    port: int
    sender: str
    username: str = ""
    password: str = ""
    starttls: bool = True

    async def send(
        self,
        to: str,
        subject: str,
        body: str,
        attachments: list[Attachment] | None = None,
    ) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        for item in attachments or []:
            main, _, sub = item.mime.partition("/")
            message.add_attachment(
                item.content,
                maintype=main,
                subtype=sub or "octet-stream",
                filename=item.filename,
            )
        await asyncio.to_thread(self._deliver, message)

    def _deliver(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
            if self.starttls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)


@dataclass
class MemoryMailer:
    """Keeps what would have been sent, for tests and local checks."""

    sent: list[dict[str, object]] = field(default_factory=list)

    async def send(
        self,
        to: str,
        subject: str,
        body: str,
        attachments: list[Attachment] | None = None,
    ) -> None:
        self.sent.append(
            {
                "to": to,
                "subject": subject,
                "body": body,
                "attachments": list(attachments or []),
            }
        )


def mailer_from(settings: Settings) -> Mailer | None:
    if not settings.smtp_host:
        return None
    return SmtpMailer(
        host=settings.smtp_host,
        port=settings.smtp_port,
        sender=settings.smtp_from or settings.smtp_username,
        username=settings.smtp_username,
        password=settings.smtp_password,
        starttls=settings.smtp_starttls,
    )
