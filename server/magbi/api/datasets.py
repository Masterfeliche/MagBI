"""Dataset and semantic-model endpoints.

``import_spec`` on create and update is still accepted and stored as a definition.
The definition itself is read and edited on ``.../definition``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, NoReturn

import duckdb
from fastapi import APIRouter, Query
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from magbi.api.deps import ServicesDep, SessionDep
from magbi.api.errors import ApiError
from magbi.api.schemas import (
    DatasetIn,
    DatasetOut,
    DatasetUpdate,
    DateTableIn,
    DefinitionIn,
    DefinitionOut,
    ImportSpec,
    MeasureIn,
    MeasureUpdate,
    RelationshipIn,
    ValidateIn,
)
from magbi.api.workspaces import get_workspace_or_404
from magbi.metadata.models import Connection, Dataset
from magbi.model.relationships import add_relationship, remove_relationship
from magbi.model.schema import (
    DatasetDefinition,
    MeasureDef,
    ModelSchemaError,
    RelationshipDef,
    definition_from_import_spec,
)
from magbi.model.validation import Issue, ValidationReport, validate_document
from magbi.refresh.dates import apply_date_table, infer_date_bounds
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


def _current(ds: Dataset) -> DatasetDefinition:
    if ds.definition is None:
        raise ApiError(422, "DATASET_NOT_CONFIGURED", "dataset has no definition")
    return DatasetDefinition.model_validate(ds.definition)


def _reject(report: ValidationReport) -> NoReturn:
    raise ApiError(
        422,
        "VALIDATION_FAILED",
        "definition has errors",
        validation=report.to_dict(),
    )


async def _store_model(
    session: AsyncSession,
    svc: ServicesDep,
    ds: Dataset,
    model_version: int,
    model: DatasetDefinition,
) -> DefinitionOut:
    return await _save_definition(
        session,
        svc.store,
        ds,
        DefinitionIn(
            model_version=model_version,
            definition=model.model_dump(mode="json", by_alias=True),
        ),
    )


@router.post(
    "/workspaces/{wid}/datasets/{did}/definition/relationships",
    response_model=DefinitionOut,
)
async def create_relationship(
    wid: uuid.UUID,
    did: uuid.UUID,
    body: RelationshipIn,
    session: SessionDep,
    svc: ServicesDep,
) -> DefinitionOut:
    ds = await get_dataset_or_404(session, wid, did)
    model = _current(ds)
    try:
        relationship = RelationshipDef.model_validate(body.relationship)
        updated = add_relationship(model, relationship)
    except (ValidationError, ModelSchemaError):
        payload = model.model_dump(mode="json", by_alias=True)
        payload["relationships"].append(body.relationship)
        _reject(_report(svc.store, ds.id, payload))
        raise AssertionError("unreachable")
    return await _store_model(session, svc, ds, body.model_version, updated)


@router.delete(
    "/workspaces/{wid}/datasets/{did}/definition/relationships/{rid}",
    response_model=DefinitionOut,
)
async def delete_relationship(
    wid: uuid.UUID,
    did: uuid.UUID,
    rid: uuid.UUID,
    session: SessionDep,
    svc: ServicesDep,
    model_version: Annotated[int, Query(ge=1)],
) -> DefinitionOut:
    ds = await get_dataset_or_404(session, wid, did)
    try:
        updated = remove_relationship(_current(ds), rid)
    except ModelSchemaError as exc:
        raise ApiError(404, "RELATIONSHIP_NOT_FOUND", str(exc)) from None
    return await _store_model(session, svc, ds, model_version, updated)


def _measure_payload(
    model: DatasetDefinition,
    table: str,
    measure: dict[str, Any],
    *,
    replace: str | None,
) -> dict[str, Any]:
    payload = model.model_dump(mode="json", by_alias=True)
    home = next((t for t in payload["tables"] if t["name"] == table), None)
    if home is None:
        raise ApiError(404, "TABLE_NOT_FOUND", f"table {table!r} does not exist")
    if replace is None:
        home["measures"].append(measure)
        return payload
    key = replace.casefold()
    kept = [m for m in home["measures"] if str(m["name"]).casefold() != key]
    if len(kept) == len(home["measures"]):
        raise ApiError(404, "MEASURE_NOT_FOUND", f"measure {replace!r} does not exist")
    kept.append(measure)
    home["measures"] = kept
    return payload


@router.post(
    "/workspaces/{wid}/datasets/{did}/definition/measures",
    response_model=DefinitionOut,
)
async def create_measure(
    wid: uuid.UUID,
    did: uuid.UUID,
    body: MeasureIn,
    session: SessionDep,
    svc: ServicesDep,
) -> DefinitionOut:
    ds = await get_dataset_or_404(session, wid, did)
    model = _current(ds)
    try:
        measure = MeasureDef.model_validate(body.measure).model_dump(mode="json")
    except ValidationError:
        _reject(
            _report(
                svc.store,
                ds.id,
                _measure_payload(model, body.table, body.measure, replace=None),
            )
        )
        raise AssertionError("unreachable")
    payload = _measure_payload(model, body.table, measure, replace=None)
    report = _report(svc.store, ds.id, payload)
    if not report.ok:
        _reject(report)
    return await _store_model(
        session, svc, ds, body.model_version, DatasetDefinition.model_validate(payload)
    )


@router.put(
    "/workspaces/{wid}/datasets/{did}/definition/measures/{name}",
    response_model=DefinitionOut,
)
async def update_measure(
    wid: uuid.UUID,
    did: uuid.UUID,
    name: str,
    body: MeasureUpdate,
    session: SessionDep,
    svc: ServicesDep,
) -> DefinitionOut:
    ds = await get_dataset_or_404(session, wid, did)
    model = _current(ds)
    found = model.measure(name)
    if found is None:
        raise ApiError(404, "MEASURE_NOT_FOUND", f"measure {name!r} does not exist")
    try:
        measure = MeasureDef.model_validate(body.measure).model_dump(mode="json")
    except ValidationError:
        _reject(
            _report(
                svc.store,
                ds.id,
                _measure_payload(model, found[0].name, body.measure, replace=name),
            )
        )
        raise AssertionError("unreachable")
    payload = _measure_payload(model, found[0].name, measure, replace=name)
    report = _report(svc.store, ds.id, payload)
    if not report.ok:
        _reject(report)
    return await _store_model(
        session, svc, ds, body.model_version, DatasetDefinition.model_validate(payload)
    )


@router.delete(
    "/workspaces/{wid}/datasets/{did}/definition/measures/{name}",
    response_model=DefinitionOut,
)
async def delete_measure(
    wid: uuid.UUID,
    did: uuid.UUID,
    name: str,
    session: SessionDep,
    svc: ServicesDep,
    model_version: Annotated[int, Query(ge=1)],
) -> DefinitionOut:
    ds = await get_dataset_or_404(session, wid, did)
    model = _current(ds)
    found = model.measure(name)
    if found is None:
        raise ApiError(404, "MEASURE_NOT_FOUND", f"measure {name!r} does not exist")
    payload = model.model_dump(mode="json", by_alias=True)
    key = name.casefold()
    for table in payload["tables"]:
        if table["name"] == found[0].name:
            table["measures"] = [
                m for m in table["measures"] if str(m["name"]).casefold() != key
            ]
    return await _store_model(
        session, svc, ds, model_version, DatasetDefinition.model_validate(payload)
    )


@router.post(
    "/workspaces/{wid}/datasets/{did}/definition/date-table",
    response_model=DefinitionOut,
)
async def create_date_table(
    wid: uuid.UUID,
    did: uuid.UUID,
    body: DateTableIn,
    session: SessionDep,
    svc: ServicesDep,
) -> DefinitionOut:
    ds = await get_dataset_or_404(session, wid, did)
    model = _current(ds)
    start, end = _date_bounds(svc.store, ds.id, model, body.start, body.end)
    try:
        updated = apply_date_table(model, start, end)
    except ModelSchemaError as exc:
        _reject(ValidationReport(errors=[Issue("DATE_TABLE_RANGE", str(exc), "error")]))
        raise AssertionError("unreachable")
    return await _store_model(session, svc, ds, body.model_version, updated)


def _date_bounds(
    store: DuckDBStore,
    dataset_id: uuid.UUID,
    model: DatasetDefinition,
    start: dt.date | None,
    end: dt.date | None,
) -> tuple[dt.date, dt.date]:
    if (start is None) != (end is None):
        raise ApiError(422, "DATE_BOUNDS_REQUIRED", "pass both start and end")
    if start is not None and end is not None:
        return start, end
    live = _open_live(store, dataset_id)
    try:
        bounds = infer_date_bounds(model, live) if live is not None else None
    finally:
        if live is not None:
            live.close()
    if bounds is None:
        raise ApiError(
            422,
            "DATE_BOUNDS_REQUIRED",
            "pass start and end; no imported date values are available",
        )
    return bounds


@router.post("/workspaces/{wid}/datasets/{did}/definition/validate")
async def validate_definition(
    wid: uuid.UUID,
    did: uuid.UUID,
    body: ValidateIn,
    session: SessionDep,
    svc: ServicesDep,
) -> dict[str, Any]:
    ds = await get_dataset_or_404(session, wid, did)
    return _report(svc.store, ds.id, body.definition).to_dict()


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
