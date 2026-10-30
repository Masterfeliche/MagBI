"""Refresh lifecycle: queue, run, record the outcome.

``run_refresh`` is a plain coroutine so the same function can be driven by
FastAPI ``BackgroundTasks`` today and wrapped in a Celery task in Sprint 8.
Blocking work (ODBC reads, DuckDB writes) runs in a worker thread.

Status flow: ``queued`` -> ``running`` -> ``succeeded`` | ``failed``. A partial
unique index allows one queued/running refresh per dataset. Failure messages are
sanitised: connector errors are already scrubbed, anything unexpected is reduced
to its type name (details go to the server log only).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from magbi.connections import ConnectionService
from magbi.connectors.errors import ConnectorError
from magbi.metadata.models import (
    Connection,
    Dataset,
    DatasetRefresh,
    RefreshStatus,
    utcnow,
)
from magbi.model.schema import (
    CsvSource,
    DatasetDefinition,
    SqlQuerySource,
    SqlTableSource,
)
from magbi.refresh.dates import attach_date_table
from magbi.refresh.file_import import carry_over_tables
from magbi.refresh.importer import (
    DEFAULT_BATCH_SIZE,
    ImportPipelineError,
    ImportResult,
    TableSpec,
    import_tables,
)
from magbi.refresh.swap import SwapError, publish_version
from magbi.storage.duckdb_store import DuckDBStore

log = logging.getLogger("magbi.refresh")

MAX_ERROR_LENGTH = 1000
STALE_MESSAGE = "interrupted by a server restart"


class RefreshConflict(Exception):
    """A refresh is already queued or running for this dataset."""

    def __init__(self, refresh_id: uuid.UUID) -> None:
        super().__init__("a refresh is already in progress for this dataset")
        self.refresh_id = refresh_id


class RefreshLimit(Exception):
    """The workspace or the platform already has too many active refreshes."""

    def __init__(self, scope: str) -> None:
        super().__init__(f"the {scope} refresh limit has been reached")
        self.scope = scope


WORKSPACE_REFRESH_LIMIT = 3
_ACTIVE = (RefreshStatus.QUEUED, RefreshStatus.RUNNING)


class RefreshSetupError(Exception):
    """The dataset cannot be refreshed as configured. Message is user-safe."""


@dataclass
class RefreshDeps:
    sessions: async_sessionmaker[AsyncSession]
    store: DuckDBStore
    connections: ConnectionService
    batch_size: int = DEFAULT_BATCH_SIZE


def sanitize_error(message: str, secrets: tuple[str, ...] = ()) -> str:
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    if len(message) > MAX_ERROR_LENGTH:
        message = message[: MAX_ERROR_LENGTH - 3] + "..."
    return message


# -- queueing ----------------------------------------------------------------


async def queue_refresh(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    trigger: str = "manual",
    *,
    platform_limit: int = 10,
) -> DatasetRefresh:
    """Create a queued refresh, or raise if one is active or a cap is full."""
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        raise RefreshSetupError("dataset does not exist")
    active = (
        await session.execute(
            select(DatasetRefresh.id).where(
                DatasetRefresh.dataset_id == dataset_id,
                DatasetRefresh.status.in_(_ACTIVE),
            )
        )
    ).scalar_one_or_none()
    if active is not None:
        raise RefreshConflict(active)
    platform = await session.scalar(
        select(func.count())
        .select_from(DatasetRefresh)
        .where(DatasetRefresh.status.in_(_ACTIVE))
    )
    if int(platform or 0) >= platform_limit:
        raise RefreshLimit("platform")
    workspace = await session.scalar(
        select(func.count())
        .select_from(DatasetRefresh)
        .join(Dataset, Dataset.id == DatasetRefresh.dataset_id)
        .where(
            Dataset.workspace_id == dataset.workspace_id,
            DatasetRefresh.status.in_(_ACTIVE),
        )
    )
    if int(workspace or 0) >= WORKSPACE_REFRESH_LIMIT:
        raise RefreshLimit("workspace")
    refresh = DatasetRefresh(dataset_id=dataset_id, trigger=trigger)
    session.add(refresh)
    try:
        await session.commit()
    except IntegrityError:
        # Lost a race with another request; the partial unique index caught it.
        await session.rollback()
        winner = (
            await session.execute(
                select(DatasetRefresh.id).where(
                    DatasetRefresh.dataset_id == dataset_id,
                    DatasetRefresh.status.in_(
                        [RefreshStatus.QUEUED, RefreshStatus.RUNNING]
                    ),
                )
            )
        ).scalar_one_or_none()
        if winner is None:
            raise
        raise RefreshConflict(winner) from None
    return refresh


# -- startup sweep -----------------------------------------------------------


async def sweep_stale_refreshes(deps: RefreshDeps) -> int:
    """Fail refreshes left queued/running by a crash and drop their staging files."""
    async with deps.sessions() as session:
        rows = (
            await session.execute(
                select(DatasetRefresh.id, DatasetRefresh.dataset_id).where(
                    DatasetRefresh.status.in_(
                        [RefreshStatus.QUEUED, RefreshStatus.RUNNING]
                    )
                )
            )
        ).all()
        if not rows:
            return 0
        await session.execute(
            update(DatasetRefresh)
            .where(DatasetRefresh.id.in_([r.id for r in rows]))
            .values(
                status=RefreshStatus.FAILED, error=STALE_MESSAGE, finished_at=utcnow()
            )
        )
        await session.commit()
    for dataset_id in {r.dataset_id for r in rows}:
        try:
            deps.store.discard_staging(str(dataset_id))
        except OSError:
            log.warning("could not remove stale staging file for %s", dataset_id)
    log.warning("marked %d stale refresh(es) as failed", len(rows))
    return len(rows)


# -- running -----------------------------------------------------------------


@dataclass
class _Job:
    dataset_id: uuid.UUID
    version: int
    kind: str
    config: dict[str, Any]
    tables: list[TableSpec]
    definition: dict[str, Any]


def _import_plan(raw: dict[str, Any] | None) -> tuple[uuid.UUID, list[TableSpec]]:
    """Tables to read from the source. Generated tables (no source) are skipped."""
    if not raw:
        raise RefreshSetupError("dataset has no tables configured for import")
    try:
        definition = DatasetDefinition.model_validate(raw)
    except ValidationError:
        raise RefreshSetupError("dataset definition is invalid") from None
    if not definition.tables:
        raise RefreshSetupError("dataset has no tables configured for import")
    if definition.connection_id is None:
        raise RefreshSetupError("dataset has no connection configured")
    specs: list[TableSpec] = []
    for table in definition.tables:
        source = table.source
        if source is None or isinstance(source, CsvSource):
            continue  # generated, or an upload carried over from the live file
        if isinstance(source, SqlQuerySource):
            specs.append(TableSpec("", table.name, table.name, query=source.sql))
            continue
        assert isinstance(source, SqlTableSource)
        specs.append(TableSpec(source.schema_, source.table, table.name))
    if not specs:
        raise RefreshSetupError("dataset has no tables configured for import")
    return definition.connection_id, specs


async def _prepare(deps: RefreshDeps, refresh_id: uuid.UUID) -> _Job | None:
    """Move queued -> running and resolve what to import. None if nothing to do."""
    async with deps.sessions() as session:
        refresh = await session.get(DatasetRefresh, refresh_id)
        if refresh is None or refresh.status is not RefreshStatus.QUEUED:
            return None
        dataset = await session.get(Dataset, refresh.dataset_id)
        refresh.status = RefreshStatus.RUNNING
        refresh.started_at = utcnow()
        refresh.version = (dataset.current_version if dataset else 0) + 1
        await session.commit()
        if dataset is None:
            raise RefreshSetupError("dataset no longer exists")

        connection_id, tables = _import_plan(dataset.definition)
        connection = await session.get(Connection, connection_id)
        if connection is None or connection.workspace_id != dataset.workspace_id:
            raise RefreshSetupError("the dataset's connection was not found")
        config = deps.connections.runtime_config(connection)
        return _Job(
            dataset.id,
            refresh.version,
            connection.kind,
            config,
            tables,
            dataset.definition or {},
        )


def _import_job(
    deps: RefreshDeps, job: _Job
) -> tuple[ImportResult, dict[str, Any] | None]:
    """Blocking: read the source into the staging file. Always cleans up on error.

    The second value is the definition to store when a date table was added.
    """
    dataset_key = str(job.dataset_id)
    deps.store.discard_staging(dataset_key)  # leftovers from an earlier crash
    connector = deps.connections.connector_for(job.kind)
    staging = None
    try:
        connector.connect(job.config)
        staging = deps.store.open_staging(dataset_key)
        result = import_tables(
            connector, job.tables, staging, batch_size=deps.batch_size
        )
        updated: dict[str, Any] | None = None
        if job.definition:
            model = DatasetDefinition.model_validate(job.definition)
            uploads = [
                table.name
                for table in model.tables
                if isinstance(table.source, CsvSource)
            ]
            carry_over_tables(deps.store, dataset_key, staging, uploads)
            extra, new_model = attach_date_table(staging, model)
            from magbi.refresh.calculated import apply_calculated_columns

            apply_calculated_columns(staging, new_model)
            if extra is not None:
                result.tables.append(extra)
            if new_model != model:
                updated = new_model.model_dump(mode="json", by_alias=True)
        return result, updated
    except BaseException:
        if staging is not None:
            staging.close()
            staging = None
        deps.store.discard_staging(dataset_key)
        raise
    finally:
        if staging is not None:
            staging.close()
        connector.close()


async def _finish(
    deps: RefreshDeps,
    refresh_id: uuid.UUID,
    status: RefreshStatus,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    async with deps.sessions() as session:
        await session.execute(
            update(DatasetRefresh)
            .where(DatasetRefresh.id == refresh_id)
            .values(status=status, result=result, error=error, finished_at=utcnow())
        )
        await session.commit()


async def run_refresh(deps: RefreshDeps, refresh_id: uuid.UUID) -> None:
    """Execute one queued refresh to completion. Never raises for job failures."""
    secrets: tuple[str, ...] = ()
    try:
        job = await _prepare(deps, refresh_id)
        if job is None:
            return
        secrets = (str(job.config.get("password") or ""),)
        started = datetime.now()
        result, definition = await asyncio.to_thread(_import_job, deps, job)
        async with deps.sessions() as session:
            await publish_version(session, deps.store, job.dataset_id, job.version)
            if definition is not None:
                await session.execute(
                    update(Dataset)
                    .where(Dataset.id == job.dataset_id)
                    .values(
                        definition=definition, model_version=Dataset.model_version + 1
                    )
                )
                await session.commit()
        summary = result.to_dict()
        summary["version"] = job.version
        summary["seconds"] = round((datetime.now() - started).total_seconds(), 3)
        await _finish(deps, refresh_id, RefreshStatus.SUCCEEDED, result=summary)
        log.info(
            "refresh %s succeeded: %d rows in %d table(s)",
            refresh_id,
            result.total_rows,
            len(result.tables),
        )
    except asyncio.CancelledError:
        await _finish(deps, refresh_id, RefreshStatus.FAILED, error="cancelled")
        raise
    except (ConnectorError, ImportPipelineError, SwapError, RefreshSetupError) as exc:
        message = sanitize_error(str(exc), secrets)
        log.warning("refresh %s failed: %s", refresh_id, message)
        await _finish(deps, refresh_id, RefreshStatus.FAILED, error=message)
    except Exception as exc:
        log.exception("refresh %s crashed", refresh_id)
        await _finish(
            deps,
            refresh_id,
            RefreshStatus.FAILED,
            error=f"unexpected error ({type(exc).__name__}); see server log",
        )
