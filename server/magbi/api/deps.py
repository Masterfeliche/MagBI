"""FastAPI dependencies shared by the routers."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magbi.api.errors import ApiError
from magbi.auth.roles import Actor, permits
from magbi.auth.tokens import EMBED_AUDIENCE, USER_AUDIENCE, TokenError, read_token
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


async def get_actor(request: Request, svc: ServicesDep, session: SessionDep) -> Actor:
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
    token = raw.strip()
    if token.startswith("v2_svc_"):
        return await _service_actor(session, token)
    cfg = svc.settings
    algorithm = "RS256" if cfg.jwt_private_key_pem else "HS256"
    try:
        payload = read_token(
            token,
            secret=cfg.jwt_secret,
            algorithm=algorithm,
            public_key=cfg.jwt_public_key_pem or None,
            audience=USER_AUDIENCE,
        )
    except TokenError as exc:
        if exc.code == "TOKEN_EXPIRED":
            raise ApiError(401, exc.code, exc.message) from None
        try:
            payload = read_token(
                token,
                secret=cfg.jwt_secret,
                algorithm=algorithm,
                public_key=cfg.jwt_public_key_pem or None,
                audience=EMBED_AUDIENCE,
            )
        except TokenError as embed_exc:
            raise ApiError(401, embed_exc.code, embed_exc.message) from None
    if payload.get("type") == "embed":
        rls = payload.get("rls") if isinstance(payload.get("rls"), dict) else {}
        roles = rls.get("roles") if isinstance(rls, dict) else []
        return Actor(
            "embed",
            str(payload.get("sub", "")),
            str(payload.get("email", "")),
            str(payload.get("name", "")),
            workspace_id=str(payload.get("workspaceId", "")),
            datasets=tuple(str(item) for item in payload.get("datasets") or []),
            reports=tuple(str(item) for item in payload.get("reports") or []),
            rls_roles=tuple(str(item) for item in roles or []),
        )
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


async def _service_actor(session: AsyncSession, token: str) -> Actor:
    from magbi.auth.service_tokens import hash_service_secret
    from magbi.metadata.models import ServiceToken

    row = await session.scalar(
        select(ServiceToken).where(
            ServiceToken.token_hash == hash_service_secret(token)
        )
    )
    if row is None or row.revoked_at is not None:
        raise ApiError(401, "TOKEN_INVALID", "token is not valid")
    return Actor(
        "service", str(row.id), "", row.name, workspace_id=str(row.workspace_id)
    )


ActorDep = Annotated[Actor, Depends(get_actor)]


_EMBED_REPORT = re.compile(r"^/api/v1/workspaces/([^/]+)/reports/([^/]+)/?$")
_EMBED_QUERY = re.compile(r"^/api/v1/workspaces/([^/]+)/datasets/([^/]+)/query/?$")
_EMBED_THEMES = re.compile(r"^/api/v1/workspaces/([^/]+)/themes/?$")


def _embed_request_allowed(method: str, path: str, actor: Actor) -> bool:
    """An embed token may read its own reports and its workspace's themes, and query its own datasets."""
    if method == "GET" and path.rstrip("/") == "/api/v1/auth/whoami":
        return True
    report = _EMBED_REPORT.match(path)
    if method == "GET" and report:
        wid, rid = report.groups()
        return wid == actor.workspace_id and rid in actor.reports
    themes = _EMBED_THEMES.match(path)
    if method == "GET" and themes:
        return themes.group(1) == actor.workspace_id
    query = _EMBED_QUERY.match(path)
    if method == "POST" and query:
        wid, did = query.groups()
        return wid == actor.workspace_id and did in actor.datasets
    return False


async def api_guard(request: Request, actor: ActorDep) -> Actor:
    """Identify the caller and keep embed and service tokens off management routes."""
    path = request.url.path
    if actor.kind == "embed" and not _embed_request_allowed(
        request.method, path, actor
    ):
        raise ApiError(403, "FORBIDDEN", "an embed token cannot call this route")
    if actor.kind == "service" and not path.endswith(("/embed/token", "/auth/whoami")):
        raise ApiError(403, "FORBIDDEN", "a service token cannot call this route")
    return actor


def _check_role(request: Request, actor: Actor, minimum: str) -> None:
    wid = request.path_params.get("wid")
    # Embed and service tokens are already confined by api_guard and the route itself.
    if wid is None or actor.kind in ("embed", "service"):
        return
    if not permits(actor, str(wid), minimum):
        raise ApiError(403, "FORBIDDEN", f"the workspace {minimum} role is required")


# Routes a person with a share or an app (and no workspace role) may read.
_GRANTED_READS = ("/workspaces/{wid}/reports/{rid}", "/workspaces/{wid}/themes")


async def workspace_access(request: Request, actor: ActorDep, session: SessionDep) -> None:
    """Reading a workspace needs viewer; any other method needs editor.

    Someone a report is shared with, or who is in a published app's audience,
    may also read that report and the workspace's themes.
    """
    minimum = "viewer" if request.method in ("GET", "HEAD") else "editor"
    try:
        _check_role(request, actor, minimum)
    except ApiError:
        if not await _granted_read(request, actor, session):
            raise


async def _granted_read(request: Request, actor: Actor, session: AsyncSession) -> bool:
    import uuid

    from magbi.sharing import report_granted, workspace_granted

    route = request.scope.get("route")
    # The route's own template; whether it carries the /api/v1 prefix varies by FastAPI version.
    template = str(getattr(route, "path", "")).removeprefix("/api/v1")
    if request.method not in ("GET", "HEAD") or template not in _GRANTED_READS:
        return False
    try:
        wid = uuid.UUID(str(request.path_params["wid"]))
        if template.endswith("{rid}"):
            return await report_granted(session, actor, wid, uuid.UUID(str(request.path_params["rid"])))
        return await workspace_granted(session, actor, wid)
    except (KeyError, ValueError):
        return False


async def connection_access(request: Request, actor: ActorDep) -> None:
    """Connections hold credentials: editors may browse them, only admins may change them."""
    minimum = "editor" if request.method in ("GET", "HEAD") else "admin"
    _check_role(request, actor, minimum)
