"""The built-in report themes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from magbi.api.errors import ApiError
from magbi.themes import load_theme, theme_ids

router = APIRouter(tags=["themes"])


@router.get("/themes")
async def list_themes() -> list[dict[str, Any]]:
    return [load_theme(theme_id) for theme_id in theme_ids()]


@router.get("/themes/{theme_id}")
async def get_theme(theme_id: str) -> dict[str, Any]:
    try:
        return load_theme(theme_id)
    except KeyError:
        raise ApiError(404, "THEME_NOT_FOUND", f"no theme {theme_id!r}") from None
