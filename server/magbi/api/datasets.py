"""Dataset endpoints (minimal: create, list, get, update).

``import_spec`` is transitional (MAGBI-002): it says which tables of which saved
connection a dataset imports. Sprint 3 replaces it with the real dataset model.
"""

from __future__ import annotations

import uuid
from typing import Any

import duckdb
from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from magbi.api.deps import ServicesDep, SessionDep
from magbi.api.errors import ApiError
from magbi.api.schemas import (
    DatasetIn,
    DatasetOut,
    DatasetUpdate,
    DefinitionIn,
    DefinitionOut,
    ImportSpec,
)
from magbi.api.workspaces import get_workspace_or_404
from magbi.metadata.models import Connection, Dataset
from magbi.model.schema import (
    DatasetDefinition,
    ModelSchemaError,
    definition_from_import_spec,
)
from magbi.model.validation import ValidationReport, validate_document
from magbi.storage.duckdb_store import DuckDBStore, StoreError

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


def _open_live(
    store: DuckDBStore, dataset_id: uuid.UUID
) -> duckdb.DuckDBPyConnection | None:
    try:
        path = store.live_path(str(dataset_id))
    except StoreError:
        return None
    if not path.is_file():
        return None
    return duckdb.connect(str(path), read_only=True)


def _report(
    store: DuckDBStore, dataset_id: uuid.UUID, raw: dict[str, Any]
) -> ValidationReport:
    live = _open_live(store, dataset_id)
    try:
        return validate_document(raw, live)
    finally:
        if live is not None:
            live.close()


async def _save_definition(
    session: AsyncSession,
    store: DuckDBStore,
    ds: Dataset,
    body: DefinitionIn,
) -> DefinitionOut:
    if ds.model_version != body.model_version:
        raise ApiError(
            409,
            "MODEL_VERSION_CONFLICT",
            f"definition is at model_version {ds.model_version}",
            model_version=ds.model_version,
        )
    report = _report(store, ds.id, body.definition)
    if not report.ok:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "definition has errors",
            validation=report.to_dict(),
        )
    model = DatasetDefinition.model_validate(body.definition)
    ds.definition = model.model_dump(mode="json", by_alias=True)
    ds.model_version += 1
    await _commit(session)
    return DefinitionOut(
        model_version=ds.model_version,
        definition=ds.definition,
        validation=report.to_dict(),
    )


@router.get("/workspaces/{wid}/datasets/{did}/definition", response_model=DefinitionOut)
async def get_definition(
    wid: uuid.UUID, did: uuid.UUID, session: SessionDep, svc: ServicesDep
) -> DefinitionOut:
    ds = await get_dataset_or_404(session, wid, did)
    validation = None
    if ds.definition is not None:
        validation = _report(svc.store, ds.id, ds.definition).to_dict()
    return DefinitionOut(
        model_version=ds.model_version, definition=ds.definition, validation=validation
    )


@router.put("/workspaces/{wid}/datasets/{did}/definition", response_model=DefinitionOut)
async def put_definition(
    wid: uuid.UUID,
    did: uuid.UUID,
    body: DefinitionIn,
    session: SessionDep,
    svc: ServicesDep,
) -> DefinitionOut:
    ds = await get_dataset_or_404(session, wid, did)
    return await _save_definition(session, svc.store, ds, body)


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
