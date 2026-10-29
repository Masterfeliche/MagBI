"""Dataset refresh trigger and history endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/refresh", tags=["refresh"])
