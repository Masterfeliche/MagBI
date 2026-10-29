"""FastAPI dependencies shared by the routers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from magbi.api.errors import ApiError
from magbi.auth.roles import Actor
from magbi.auth.tokens import USER_AUDIENCE, TokenError, read_token
from magbi.services import Services


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


async def get_session(svc: ServicesDep) -> AsyncIterator[AsyncSession]:
    async with svc.sessions() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _dev_actor() -> Actor:
    return Actor("dev", "dev", "dev@localhost", "Dev", platform_admin=True)


async def get_actor(request: Request, svc: ServicesDep) -> Actor:
    """The caller. A missing token is the dev admin only in test or insecure mode."""
    header = request.headers.get("authorization", "")
    if not header:
        cfg = svc.settings
        if cfg.environment == "test" or cfg.insecure_admin_api:
            return _dev_actor()
        raise ApiError(401, "TOKEN_MISSING", "authentication is required")
    scheme, _, raw = header.partition(" ")
    if scheme.lower() != "bearer" or not raw:
        raise ApiError(401, "TOKEN_INVALID", "authentication is required")
    cfg = svc.settings
    algorithm = "RS256" if cfg.jwt_private_key_pem else "HS256"
    try:
        payload = read_token(
            raw.strip(),
            secret=cfg.jwt_secret,
            algorithm=algorithm,
            public_key=cfg.jwt_public_key_pem or None,
            audience=USER_AUDIENCE,
        )
    except TokenError as exc:
        raise ApiError(401, exc.code, exc.message) from None
    if payload.get("type") != "user":
        raise ApiError(401, "TOKEN_INVALID", "token is not valid")
    workspaces = payload.get("workspaces") or []
    memberships = tuple(
        (str(item["id"]), str(item["role"]))
        for item in workspaces
        if isinstance(item, dict)
    )
    return Actor(
        "user",
        str(payload.get("sub", "")),
        str(payload.get("email", "")),
        str(payload.get("name", "")),
        platform_admin=bool(payload.get("platformAdmin")),
        memberships=memberships,
    )


ActorDep = Annotated[Actor, Depends(get_actor)]


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
