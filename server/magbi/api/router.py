"""The versioned API (``/api/v1``) per docs/architecture/API-SERVICE-SPEC.md."""

from fastapi import APIRouter, Depends

from magbi.api import (
    admin,
    connections,
    datasets,
    embed,
    identity,
    query,
    refresh,
    reports,
    transforms,
    workspaces,
)
from magbi.api.deps import api_guard

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(api_guard)])
api_router.include_router(connections.router)
api_router.include_router(workspaces.router)
api_router.include_router(identity.router)
api_router.include_router(admin.router)
api_router.include_router(embed.router)
api_router.include_router(datasets.router)
api_router.include_router(refresh.router)
api_router.include_router(query.router)
api_router.include_router(reports.router)
api_router.include_router(transforms.router)
