"""Mint an embed token from a workspace service token."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from magbi.api.deps import ActorDep, ServicesDep, SessionDep
from magbi.api.errors import ApiError
from magbi.auth.roles import permits_service
from magbi.auth.tokens import embed_claims, issue_token
from magbi.metadata.models import Dataset, Report

router = APIRouter(tags=["embed"])


class RlsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: list[str] = Field(default_factory=list)


class EmbedIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    user_email: str = Field(alias="userEmail", min_length=3)
    user_name: str = Field(alias="userName", min_length=1)
    reports: list[uuid.UUID] = Field(default_factory=list)
    datasets: list[uuid.UUID] = Field(min_length=1)
    rls: RlsIn = Field(default_factory=RlsIn)
    ttl: int | None = Field(default=None, ge=60)


@router.post("/embed/token")
async def create_embed_token(
    body: EmbedIn, session: SessionDep, svc: ServicesDep, actor: ActorDep
) -> dict[str, Any]:
    if actor.workspace_id is None or not permits_service(actor, actor.workspace_id):
        raise ApiError(403, "FORBIDDEN", "a service token is required")
    workspace_id = uuid.UUID(actor.workspace_id)
    await _datasets(session, body.datasets, workspace_id)
    await _reports(session, body.reports, workspace_id)
    cap = svc.settings.embed_token_ttl_minutes * 60
    seconds = cap if body.ttl is None else min(body.ttl, cap)
    minutes = max(1, seconds // 60)
    claims = embed_claims(
        email=body.user_email.strip().lower(),
        name=body.user_name.strip(),
        workspace_id=str(workspace_id),
        reports=[str(item) for item in body.reports],
        datasets=[str(item) for item in body.datasets],
        roles=list(body.rls.roles),
        ttl_minutes=minutes,
    )
    algorithm = "RS256" if svc.settings.jwt_private_key_pem else "HS256"
    token = issue_token(
        claims,
        secret=svc.settings.jwt_secret,
        algorithm=algorithm,
        private_key=svc.settings.jwt_private_key_pem or None,
    )
    return {
        "token": token,
        "expiresAt": (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(),
        "reportUrls": {str(item): f"/embed/{item}" for item in body.reports},
    }


async def _datasets(
    session: SessionDep, ids: list[uuid.UUID], workspace_id: uuid.UUID
) -> None:
    rows = await session.scalars(
        select(Dataset).where(Dataset.id.in_(ids), Dataset.workspace_id == workspace_id)
    )
    found = {row.id for row in rows}
    missing = [item for item in ids if item not in found]
    if missing:
        raise ApiError(
            422,
            "OUTSIDE_WORKSPACE",
            f"dataset {missing[0]} is not in this workspace",
        )


async def _reports(
    session: SessionDep, ids: list[uuid.UUID], workspace_id: uuid.UUID
) -> None:
    if not ids:
        return
    rows = await session.scalars(
        select(Report).where(Report.id.in_(ids), Report.workspace_id == workspace_id)
    )
    found = {row.id for row in rows}
    missing = [item for item in ids if item not in found]
    if missing:
        raise ApiError(
            422, "OUTSIDE_WORKSPACE", f"report {missing[0]} is not in this workspace"
        )
