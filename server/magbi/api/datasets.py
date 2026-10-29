"""Dataset endpoints (minimal: create, list, get, update).

``import_spec`` is transitional (MAGBI-002): it says which tables of which saved
connection a dataset imports. Sprint 3 replaces it with the real dataset model.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from magbi.api.deps import SessionDep
from magbi.api.errors import ApiError
from magbi.api.schemas import DatasetIn, DatasetOut, DatasetUpdate, ImportSpec
from magbi.api.workspaces import get_workspace_or_404
from magbi.metadata.models import Connection, Dataset
from magbi.model.schema import ModelSchemaError, definition_from_import_spec

router = APIRouter(tags=["datasets"])


async def get_dataset_or_404(
    session: AsyncSession, wid: uuid.UUID, did: uuid.UUID
) -> Dataset:
    ds = await session.get(Dataset, did)
    if ds is None or ds.workspace_id != wid:
        raise ApiError(404, "DATASET_NOT_FOUND", "dataset not found")
    return ds


async def _definition_from_spec(
    session: AsyncSession, wid: uuid.UUID, spec: ImportSpec
) -> dict[str, Any]:
    """Accept the Sprint 2 import_spec body and store a real definition."""
    connection = await session.get(Connection, spec.connection_id)
    if connection is None or connection.workspace_id != wid:
        raise ApiError(
            422, "CONNECTION_NOT_FOUND", "import_spec.connection_id does not exist"
        )
    try:
        definition = definition_from_import_spec(spec.model_dump(by_alias=True))
    except (ModelSchemaError, KeyError, ValueError) as exc:
        raise ApiError(422, "INVALID_IMPORT_SPEC", str(exc)) from None
    return definition.model_dump(mode="json", by_alias=True)


def _out(ds: Dataset) -> DatasetOut:
    return DatasetOut(
        id=ds.id,
        workspace_id=ds.workspace_id,
        name=ds.name,
        description=ds.description,
        mode=ds.mode.value,
        current_version=ds.current_version,
        model_version=ds.model_version,
        definition=ds.definition,
        created_at=ds.created_at,
        updated_at=ds.updated_at,
    )


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ApiError(
            409, "DATASET_EXISTS", "a dataset with this name already exists"
        ) from None


@router.post("/workspaces/{wid}/datasets", status_code=201, response_model=DatasetOut)
async def create_dataset(
    wid: uuid.UUID, body: DatasetIn, session: SessionDep
) -> DatasetOut:
    await get_workspace_or_404(session, wid)
    ds = Dataset(workspace_id=wid, name=body.name.strip(), description=body.description)
    if body.import_spec is not None:
        ds.definition = await _definition_from_spec(session, wid, body.import_spec)
    session.add(ds)
    await _commit(session)
    return _out(ds)


@router.get("/workspaces/{wid}/datasets", response_model=list[DatasetOut])
async def list_datasets(wid: uuid.UUID, session: SessionDep) -> list[DatasetOut]:
    await get_workspace_or_404(session, wid)
    rows = await session.execute(
        select(Dataset).where(Dataset.workspace_id == wid).order_by(Dataset.name)
    )
    return [_out(d) for d in rows.scalars()]


@router.get("/workspaces/{wid}/datasets/{did}", response_model=DatasetOut)
async def get_dataset(
    wid: uuid.UUID, did: uuid.UUID, session: SessionDep
) -> DatasetOut:
    return _out(await get_dataset_or_404(session, wid, did))


@router.put("/workspaces/{wid}/datasets/{did}", response_model=DatasetOut)
async def update_dataset(
    wid: uuid.UUID, did: uuid.UUID, body: DatasetUpdate, session: SessionDep
) -> DatasetOut:
    ds = await get_dataset_or_404(session, wid, did)
    if body.name is not None:
        ds.name = body.name.strip()
    if body.description is not None:
        ds.description = body.description
    if body.import_spec is not None:
        ds.definition = await _definition_from_spec(session, wid, body.import_spec)
        ds.model_version += 1
    await _commit(session)
    return _out(ds)
