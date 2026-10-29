"""Admin endpoints — users, audit log, metrics, service tokens."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/admin", tags=["admin"])
