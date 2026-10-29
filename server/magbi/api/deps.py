"""FastAPI dependencies shared by the routers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from magbi.api.errors import ApiError
from magbi.services import Services


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


async def get_session(svc: ServicesDep) -> AsyncIterator[AsyncSession]:
    async with svc.sessions() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def admin_gate(svc: ServicesDep) -> None:
    """Keep the unauthenticated admin API off outside dev unless opted in.

    Until user auth lands (Sprint 7) these endpoints can make the server connect
    to arbitrary hosts, so exposing them must be a deliberate choice
    (``MAGBI_INSECURE_ADMIN_API=true``). Replaced by role checks in Sprint 7.
    """
    cfg = svc.settings
    if cfg.environment != "dev" and not cfg.insecure_admin_api:
        raise ApiError(
            503,
            "ADMIN_API_DISABLED",
            "this API has no authentication yet; set MAGBI_INSECURE_ADMIN_API=true "
            "to enable it outside dev",
        )
