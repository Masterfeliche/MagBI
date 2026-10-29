"""Embed token generation and iframe endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/embed", tags=["embed"])
