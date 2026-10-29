"""The versioned API (``/api/v1``) per docs/architecture/API-SERVICE-SPEC.md."""

from fastapi import APIRouter, Depends

from magbi.api import connections, datasets, refresh, workspaces
from magbi.api.deps import admin_gate

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(admin_gate)])
api_router.include_router(connections.router)
api_router.include_router(workspaces.router)
api_router.include_router(datasets.router)
api_router.include_router(refresh.router)
