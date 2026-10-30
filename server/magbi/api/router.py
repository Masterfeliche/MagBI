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
from magbi.api.deps import api_guard, connection_access, workspace_access

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(api_guard)])
# Workspace routes check the caller's role. Query does its own check, because a
# viewer may POST a query and only an editor may set query roles.
workspace_role = [Depends(workspace_access)]
api_router.include_router(connections.router, dependencies=[Depends(connection_access)])
api_router.include_router(workspaces.router, dependencies=workspace_role)
api_router.include_router(identity.router)
api_router.include_router(admin.router)
api_router.include_router(embed.router)
api_router.include_router(datasets.router, dependencies=workspace_role)
api_router.include_router(refresh.router, dependencies=workspace_role)
api_router.include_router(query.router)
api_router.include_router(reports.router, dependencies=workspace_role)
api_router.include_router(transforms.router, dependencies=workspace_role)
