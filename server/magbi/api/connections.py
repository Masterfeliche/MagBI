"""Connection endpoints (browse, test, CRUD)."""

from fastapi import APIRouter

from magbi.connections import ConnectionService

router = APIRouter(tags=["connections"])


@router.get("/connection-kinds")
async def connection_kinds() -> dict[str, list[str]]:
    return {"kinds": ConnectionService.supported_kinds()}
