"""Workspace endpoints (minimal: create, list, get)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from magbi.api.deps import ActorDep, SessionDep
from magbi.api.errors import ApiError
from magbi.api.schemas import WorkspaceIn, WorkspaceOut
from magbi.auth.roles import permits
from magbi.metadata.models import Role, User, Workspace, WorkspaceMember

router = APIRouter(tags=["workspaces"])


async def get_workspace_or_404(session: SessionDep, wid: uuid.UUID) -> Workspace:
    ws = await session.get(Workspace, wid)
    if ws is None:
        raise ApiError(404, "WORKSPACE_NOT_FOUND", "workspace not found")
    return ws


@router.post("/workspaces", status_code=201, response_model=WorkspaceOut)
async def create_workspace(body: WorkspaceIn, session: SessionDep) -> Workspace:
    ws = Workspace(name=body.name.strip(), description=body.description)
    session.add(ws)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ApiError(
            409, "WORKSPACE_EXISTS", "a workspace with this name already exists"
        ) from None
    return ws


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(session: SessionDep) -> list[Workspace]:
    rows = await session.execute(select(Workspace).order_by(Workspace.name))
    return list(rows.scalars())


@router.get("/workspaces/{wid}", response_model=WorkspaceOut)
async def get_workspace(wid: uuid.UUID, session: SessionDep) -> Workspace:
    return await get_workspace_or_404(session, wid)


class MemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3)
    role: Literal["admin", "editor", "viewer"]


def _require_admin(actor: ActorDep, wid: uuid.UUID) -> None:
    if not permits(actor, str(wid), "admin"):
        raise ApiError(403, "FORBIDDEN", "a workspace admin is required")


@router.post("/workspaces/{wid}/members", status_code=201)
async def add_member(
    wid: uuid.UUID, body: MemberIn, session: SessionDep, actor: ActorDep
) -> dict[str, str]:
    _require_admin(actor, wid)
    await get_workspace_or_404(session, wid)
    user = await session.scalar(
        select(User).where(User.email == body.email.strip().lower())
    )
    if user is None:
        raise ApiError(404, "USER_NOT_FOUND", "user not found")
    existing = await session.get(WorkspaceMember, (wid, user.id))
    if existing is not None:
        raise ApiError(409, "MEMBER_EXISTS", "the user is already a member")
    session.add(
        WorkspaceMember(workspace_id=wid, user_id=user.id, role=Role(body.role))
    )
    await session.commit()
    return {"email": user.email, "role": body.role}


@router.delete("/workspaces/{wid}/members/{user_id}", status_code=204)
async def remove_member(
    wid: uuid.UUID, user_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> None:
    _require_admin(actor, wid)
    member = await session.get(WorkspaceMember, (wid, user_id))
    if member is None:
        raise ApiError(404, "MEMBER_NOT_FOUND", "member not found")
    await session.delete(member)
    await session.commit()
