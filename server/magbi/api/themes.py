"""Report themes: the built-in ones, the organisation's, and each workspace's.

A saved theme is a ``magbi.theme/1`` layer that extends a built-in theme. It
must pass the theme checks before it is stored. The organisation may mark its
default theme locked: reports then keep the brand and may change chart colours only.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from magbi.api.deps import ActorDep, SessionDep
from magbi.api.errors import ApiError
from magbi.metadata.models import AuditLog, Theme
from magbi.themes import DEFAULT_THEME, load_theme, merge, theme_ids
from magbi.themes.validate import problems

router = APIRouter(tags=["themes"])
workspace_router = APIRouter(tags=["themes"])

# Keys a saved layer may not set: they belong to the row, not the theme.
ROW_KEYS = ("id", "extends", "locked", "scope", "$schema")


class ThemeIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    definition: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = Field(default=False, alias="isDefault")
    locked: bool = False


def full_theme(definition: dict[str, Any]) -> dict[str, Any]:
    """The complete theme a saved layer stands for; 422 when it fails the checks."""
    base = definition.get("extends", DEFAULT_THEME)
    if base not in theme_ids():
        raise ApiError(422, "THEME_BASE_UNKNOWN", f"a theme must extend a built-in theme, not {base!r}")
    theme = merge(load_theme(base), {key: value for key, value in definition.items() if key not in ROW_KEYS})
    try:
        found = problems(theme)
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError(422, "THEME_INVALID", f"the theme is incomplete or malformed: {exc}") from None
    if found:
        raise ApiError(422, "THEME_FAILS_CHECKS", "the theme fails the readability and colour checks", problems=found)
    return theme


def theme_out(theme: Theme) -> dict[str, Any]:
    return {
        "id": str(theme.id),
        "scope": "workspace" if theme.workspace_id else "organisation",
        "workspaceId": str(theme.workspace_id) if theme.workspace_id else None,
        "name": theme.name,
        "definition": theme.definition,
        "isDefault": theme.is_default,
        "locked": theme.locked,
        "version": theme.version,
        "updatedBy": theme.updated_by,
        "updatedAt": theme.updated_at.isoformat() if theme.updated_at else None,
    }


def _require_platform(actor: ActorDep) -> None:
    if actor.kind != "dev" and not actor.platform_admin:
        raise ApiError(403, "FORBIDDEN", "a platform admin is required to change organisation themes")


async def _scoped(session: SessionDep, workspace_id: uuid.UUID | None) -> list[Theme]:
    clause = Theme.workspace_id.is_(None) if workspace_id is None else Theme.workspace_id == workspace_id
    rows = await session.execute(select(Theme).where(clause).order_by(Theme.name))
    return list(rows.scalars())


async def _save(session: SessionDep, actor: ActorDep, theme: Theme | None, body: ThemeIn, workspace_id: uuid.UUID | None) -> Theme:
    if body.locked and workspace_id is not None:
        raise ApiError(422, "THEME_LOCK_ORGANISATION_ONLY", "only the organisation's theme can be locked")
    full_theme(body.definition)
    if body.is_default:
        clause = Theme.workspace_id.is_(None) if workspace_id is None else Theme.workspace_id == workspace_id
        await session.execute(update(Theme).where(clause).values(is_default=False))
    previous = None
    if theme is None:
        theme = Theme(workspace_id=workspace_id, version=1)
        session.add(theme)
        action = "theme_create"
    else:
        previous = {"version": theme.version, "definition": theme.definition}
        theme.version += 1
        action = "theme_update"
    theme.name = body.name
    theme.definition = body.definition
    theme.is_default = body.is_default
    theme.locked = body.locked and body.is_default
    theme.updated_by = actor.email or actor.subject
    await session.flush()
    session.add(AuditLog(principal=theme.updated_by, action=action, object_type="theme", object_id=str(theme.id),
                         detail={"version": theme.version, "previous": previous}))
    await session.commit()
    await session.refresh(theme)
    return theme


async def _get(session: SessionDep, tid: uuid.UUID, workspace_id: uuid.UUID | None) -> Theme:
    theme = await session.get(Theme, tid)
    if theme is None or theme.workspace_id != workspace_id:
        raise ApiError(404, "THEME_NOT_FOUND", "theme not found")
    return theme


async def _delete(session: SessionDep, actor: ActorDep, theme: Theme) -> Response:
    session.add(AuditLog(principal=actor.email or actor.subject, action="theme_delete", object_type="theme",
                         object_id=str(theme.id), detail={"version": theme.version, "definition": theme.definition}))
    await session.delete(theme)
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- built-in


@router.get("/themes")
async def list_themes() -> list[dict[str, Any]]:
    return [load_theme(theme_id) for theme_id in theme_ids()]


@router.get("/themes/{theme_id}")
async def get_theme(theme_id: str) -> dict[str, Any]:
    try:
        return load_theme(theme_id)
    except KeyError:
        raise ApiError(404, "THEME_NOT_FOUND", f"no theme {theme_id!r}") from None


# ---------------------------------------------------------------- organisation


@router.get("/organisation/themes")
async def list_organisation_themes(session: SessionDep) -> list[dict[str, Any]]:
    return [theme_out(theme) for theme in await _scoped(session, None)]


@router.post("/organisation/themes", status_code=201)
async def create_organisation_theme(body: ThemeIn, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    _require_platform(actor)
    return theme_out(await _save(session, actor, None, body, None))


@router.put("/organisation/themes/{tid}")
async def update_organisation_theme(tid: uuid.UUID, body: ThemeIn, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    _require_platform(actor)
    return theme_out(await _save(session, actor, await _get(session, tid, None), body, None))


@router.delete("/organisation/themes/{tid}", status_code=204)
async def delete_organisation_theme(tid: uuid.UUID, session: SessionDep, actor: ActorDep) -> Response:
    _require_platform(actor)
    return await _delete(session, actor, await _get(session, tid, None))


# ---------------------------------------------------------------- workspace


@workspace_router.get("/workspaces/{wid}/themes")
async def list_workspace_themes(wid: uuid.UUID, session: SessionDep) -> dict[str, list[dict[str, Any]]]:
    """The organisation's themes and this workspace's, which is everything a report here may use."""
    return {
        "organisation": [theme_out(theme) for theme in await _scoped(session, None)],
        "workspace": [theme_out(theme) for theme in await _scoped(session, wid)],
    }


@workspace_router.post("/workspaces/{wid}/themes", status_code=201)
async def create_workspace_theme(wid: uuid.UUID, body: ThemeIn, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    return theme_out(await _save(session, actor, None, body, wid))


@workspace_router.put("/workspaces/{wid}/themes/{tid}")
async def update_workspace_theme(wid: uuid.UUID, tid: uuid.UUID, body: ThemeIn, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    return theme_out(await _save(session, actor, await _get(session, tid, wid), body, wid))


@workspace_router.delete("/workspaces/{wid}/themes/{tid}", status_code=204)
async def delete_workspace_theme(wid: uuid.UUID, tid: uuid.UUID, session: SessionDep, actor: ActorDep) -> Response:
    return await _delete(session, actor, await _get(session, tid, wid))
