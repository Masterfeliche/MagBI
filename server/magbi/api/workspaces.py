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
from magbi.auth.roles import Actor, permits, role_of
from magbi.metadata.models import Role, User, Workspace, WorkspaceMember

router = APIRouter(tags=["workspaces"])


async def get_workspace_or_404(session: SessionDep, wid: uuid.UUID) -> Workspace:
    ws = await session.get(Workspace, wid)
    if ws is None:
        raise ApiError(404, "WORKSPACE_NOT_FOUND", "workspace not found")
    return ws


@router.post("/workspaces", status_code=201, response_model=WorkspaceOut)
async def create_workspace(
    body: WorkspaceIn, session: SessionDep, actor: ActorDep
) -> Workspace:
    if actor.kind != "dev" and not actor.platform_admin:
        raise ApiError(403, "FORBIDDEN", "a platform admin is required")
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


def _out(ws: Workspace, actor: Actor) -> WorkspaceOut:
    out = WorkspaceOut.model_validate(ws)
    out.my_role = role_of(actor, str(ws.id))
    return out


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(session: SessionDep, actor: ActorDep) -> list[WorkspaceOut]:
    rows = await session.execute(select(Workspace).order_by(Workspace.name))
    return [_out(ws, actor) for ws in rows.scalars() if permits(actor, str(ws.id), "viewer")]


@router.get("/workspaces/{wid}", response_model=WorkspaceOut)
async def get_workspace(wid: uuid.UUID, session: SessionDep, actor: ActorDep) -> WorkspaceOut:
    return _out(await get_workspace_or_404(session, wid), actor)


class MemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3)
    role: Literal["admin", "editor", "viewer"]


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str
    role: str


@router.get("/workspaces/{wid}/members", response_model=list[MemberOut])
async def list_members(
    wid: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[MemberOut]:
    await get_workspace_or_404(session, wid)
    if not permits(actor, str(wid), "viewer"):
        raise ApiError(403, "FORBIDDEN", "workspace membership is required")
    rows = await session.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == wid)
        .order_by(User.email)
    )
    return [
        MemberOut(
            user_id=member.user_id,
            email=user.email,
            name=user.name,
            role=member.role.value,
        )
        for member, user in rows.all()
    ]


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
