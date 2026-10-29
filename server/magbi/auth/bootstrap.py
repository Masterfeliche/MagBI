"""Create the first platform admin when the user table is empty."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from magbi.auth.tokens import hash_password
from magbi.config import Settings
from magbi.metadata.models import User


async def ensure_bootstrap_admin(
    sessions: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        return
    async with sessions() as session:
        count = await session.scalar(select(func.count()).select_from(User))
        if count:
            return
        session.add(
            User(
                email=settings.bootstrap_admin_email.strip().lower(),
                name="Admin",
                password_hash=hash_password(settings.bootstrap_admin_password),
                is_active=True,
                is_platform_admin=True,
            )
        )
        await session.commit()
