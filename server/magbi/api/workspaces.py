"""Workspace endpoints (minimal: create, list, get)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from magbi.api.deps import SessionDep
from magbi.api.errors import ApiError
from magbi.api.schemas import WorkspaceIn, WorkspaceOut
from magbi.metadata.models import Workspace

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
