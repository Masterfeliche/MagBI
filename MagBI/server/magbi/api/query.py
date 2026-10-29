"""Semantic query execution endpoint."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/query", tags=["query"])
