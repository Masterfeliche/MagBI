"""Preview a transform recipe against a dataset's imported table."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from magbi.api.datasets import get_dataset_or_404
from magbi.api.deps import ServicesDep, SessionDep
from magbi.api.errors import ApiError
from magbi.model.schema import DatasetDefinition
from magbi.transforms.errors import TransformError
from magbi.transforms.executor import preview
from magbi.transforms.steps import parse_steps

router = APIRouter(tags=["transforms"])


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str = Field(min_length=1)
    steps: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/workspaces/{wid}/datasets/{did}/transforms/preview")
async def preview_transforms(
    wid: uuid.UUID,
    did: uuid.UUID,
    body: PreviewIn,
    session: SessionDep,
    svc: ServicesDep,
) -> dict[str, Any]:
    dataset = await get_dataset_or_404(session, wid, did)
    if dataset.definition is None:
        raise ApiError(422, "NO_DEFINITION", "dataset has no definition")
    model = DatasetDefinition.model_validate(dataset.definition)
    try:
        steps = parse_steps(body.steps)
    except TransformError as exc:
        raise ApiError(422, exc.code, exc.message) from None
    if model.table(body.table) is None:
        raise ApiError(422, "UNKNOWN_TABLE", f"table {body.table!r} does not exist")
    if not svc.store.exists(str(dataset.id)):
        raise ApiError(409, "DATA_NOT_READY", "dataset has no imported data")
    con = svc.store.open_live(str(dataset.id))
    try:
        found = con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position",
            [body.table],
        ).fetchall()
        if not found:
            raise ApiError(
                409,
                "DATA_NOT_READY",
                f"table {body.table!r} is not in the imported data",
            )
        try:
            return preview(con, body.table, tuple(str(row[0]) for row in found), steps)
        except TransformError as exc:
            raise ApiError(422, exc.code, exc.message) from None
    finally:
        con.close()
