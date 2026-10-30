"""Platform-admin routes for users' service tokens."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from magbi.api.deps import ActorDep, SessionDep
from magbi.api.errors import ApiError
from magbi.auth.service_tokens import new_service_secret
from magbi.metadata.models import ServiceToken, Workspace

router = APIRouter(tags=["admin"])


class ServiceTokenIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    workspace_id: uuid.UUID = Field(alias="workspaceId")
    name: str = Field(min_length=1, max_length=200)


def _require_platform(actor: ActorDep) -> None:
    if actor.kind != "dev" and not actor.platform_admin:
        raise ApiError(403, "FORBIDDEN", "a platform admin is required")


@router.post("/admin/service-tokens", status_code=201)
async def create_service_token(
    body: ServiceTokenIn, session: SessionDep, actor: ActorDep
) -> dict[str, str]:
    _require_platform(actor)
    workspace = await session.get(Workspace, body.workspace_id)
    if workspace is None:
        raise ApiError(404, "WORKSPACE_NOT_FOUND", "workspace not found")
    secret, digest = new_service_secret()
    row = ServiceToken(
        workspace_id=workspace.id, name=body.name.strip(), token_hash=digest
    )
    session.add(row)
    await session.commit()
    return {
        "id": str(row.id),
        "token": secret,
        "workspaceId": str(workspace.id),
        "name": row.name,
    }


@router.get("/admin/service-tokens")
async def list_service_tokens(
    session: SessionDep, actor: ActorDep
) -> list[dict[str, object]]:
    _require_platform(actor)
    rows = await session.scalars(select(ServiceToken).order_by(ServiceToken.created_at))
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "workspaceId": str(row.workspace_id),
            "revoked": row.revoked_at is not None,
        }
        for row in rows
    ]


@router.delete("/admin/service-tokens/{token_id}", status_code=204)
async def revoke_service_token(
    token_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> None:
    _require_platform(actor)
    row = await session.get(ServiceToken, token_id)
    if row is None:
        raise ApiError(404, "TOKEN_NOT_FOUND", "service token not found")
    row.revoked_at = datetime.now(UTC)
    await session.commit()
