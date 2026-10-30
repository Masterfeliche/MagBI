"""Connection endpoints: test, CRUD, and browsing the source catalog.

Connectors are blocking (ODBC), so every source call runs in a worker thread and
the connector is always closed. Passwords are never returned: responses show
``"password": "***"``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from magbi.api.deps import ServicesDep, SessionDep
from magbi.api.errors import ApiError
from magbi.api.schemas import (
    DEFAULT_PREVIEW_ROWS,
    MAX_PREVIEW_ROWS,
    ConnectionIn,
    ConnectionTestIn,
    ConnectionUpdate,
    jsonable,
)
from magbi.api.workspaces import get_workspace_or_404
from magbi.connections import ConnectionService
from magbi.connectors.base import Connector, SourceTable
from magbi.connectors.types import plan_columns
from magbi.metadata.models import Connection

router = APIRouter(tags=["connections"])
T = TypeVar("T")


@router.get("/connection-kinds")
async def connection_kinds() -> dict[str, list[str]]:
    return {"kinds": ConnectionService.supported_kinds()}


async def get_connection_or_404(
    session: AsyncSession, wid: uuid.UUID, cid: uuid.UUID
) -> Connection:
    conn = await session.get(Connection, cid)
    if conn is None or conn.workspace_id != wid:
        raise ApiError(404, "CONNECTION_NOT_FOUND", "connection not found")
    return conn


async def _with_connector(
    svc: ServicesDep, connection: Connection, fn: Callable[[Connector], T]
) -> T:
    """Connect, run ``fn`` in a worker thread, always close."""
    config = svc.connections.runtime_config(connection)
    connector = svc.connections.connector_for(connection.kind)

    def run() -> T:
        connector.connect(config)
        try:
            return fn(connector)
        finally:
            connector.close()

    return await asyncio.to_thread(run)


# -- test ----------------------------------------------------------------------


@router.post("/workspaces/{wid}/connections/test")
async def test_connection(
    wid: uuid.UUID, body: ConnectionTestIn, svc: ServicesDep, session: SessionDep
) -> dict[str, Any]:
    """Try a config without saving it. Connect failures are a result, not an HTTP error."""
    await get_workspace_or_404(session, wid)
    svc.connections.validate(body.kind, body.config)  # 422 on bad config / host
    connector = svc.connections.connector_for(body.kind)
    result = await asyncio.to_thread(connector.test_connection, body.config)
    out = asdict(result)
    out["code"] = result.code.value if result.code else None
    return out


# -- CRUD ----------------------------------------------------------------------


@router.post("/workspaces/{wid}/connections", status_code=201)
async def create_connection(
    wid: uuid.UUID, body: ConnectionIn, svc: ServicesDep, session: SessionDep
) -> dict[str, Any]:
    await get_workspace_or_404(session, wid)
    cid = uuid.uuid4()
    public, secret = svc.connections.prepare(body.kind, body.config, connection_id=cid)
    conn = Connection(
        id=cid,
        workspace_id=wid,
        name=body.name.strip(),
        kind=body.kind,
        config=public,
        secret_encrypted=secret,
    )
    session.add(conn)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ApiError(
            409, "CONNECTION_EXISTS", "a connection with this name already exists"
        ) from None
    return svc.connections.public_view(conn)


@router.get("/workspaces/{wid}/connections")
async def list_connections(
    wid: uuid.UUID, svc: ServicesDep, session: SessionDep
) -> list[dict[str, Any]]:
    await get_workspace_or_404(session, wid)
    rows = await session.execute(
        select(Connection)
        .where(Connection.workspace_id == wid)
        .order_by(Connection.name)
    )
    return [svc.connections.public_view(c) for c in rows.scalars()]


@router.get("/workspaces/{wid}/connections/{cid}")
async def get_connection(
    wid: uuid.UUID, cid: uuid.UUID, svc: ServicesDep, session: SessionDep
) -> dict[str, Any]:
    return svc.connections.public_view(await get_connection_or_404(session, wid, cid))


@router.put("/workspaces/{wid}/connections/{cid}")
async def update_connection(
    wid: uuid.UUID,
    cid: uuid.UUID,
    body: ConnectionUpdate,
    svc: ServicesDep,
    session: SessionDep,
) -> dict[str, Any]:
    """Rename and/or replace the config. A missing or ``"***"`` password keeps the old one."""
    conn = await get_connection_or_404(session, wid, cid)
    if body.config is not None:
        public, secret = svc.connections.prepare(
            conn.kind,
            body.config,
            connection_id=conn.id,
            existing_secret=conn.secret_encrypted,
        )
        conn.config, conn.secret_encrypted = public, secret
    if body.name is not None:
        conn.name = body.name.strip()
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ApiError(
            409, "CONNECTION_EXISTS", "a connection with this name already exists"
        ) from None
    return svc.connections.public_view(conn)


# -- browsing the source ---------------------------------------------------------


def _table_json(table: SourceTable) -> dict[str, Any]:
    plans = {p.column: p for p in plan_columns(table.columns)}
    return {
        "schema": table.schema,
        "name": table.name,
        "kind": table.kind,
        "estimated_rows": table.estimated_rows,
        "columns": [
            {
                "name": c.name,
                "source_type": c.data_type,
                "data_type": plans[c.name].data_type.value,
                "nullable": c.is_nullable,
                "primary_key": c.is_primary_key,
                "warning": plans[c.name].warning,
            }
            for c in table.columns
        ],
    }


@router.get("/workspaces/{wid}/connections/{cid}/schemas")
async def list_schemas(
    wid: uuid.UUID, cid: uuid.UUID, svc: ServicesDep, session: SessionDep
) -> dict[str, list[str]]:
    conn = await get_connection_or_404(session, wid, cid)
    schemas = await _with_connector(svc, conn, lambda c: c.list_schemas())
    return {"schemas": schemas}


@router.get("/workspaces/{wid}/connections/{cid}/tables")
async def list_tables(
    wid: uuid.UUID,
    cid: uuid.UUID,
    schema: Annotated[str, Query(min_length=1, max_length=128)],
    svc: ServicesDep,
    session: SessionDep,
) -> dict[str, Any]:
    conn = await get_connection_or_404(session, wid, cid)
    tables = await _with_connector(svc, conn, lambda c: c.list_tables(schema))
    return {"tables": [_table_json(t) for t in tables]}


@router.get("/workspaces/{wid}/connections/{cid}/tables/{schema}/{table}/preview")
async def preview_table(
    wid: uuid.UUID,
    cid: uuid.UUID,
    schema: str,
    table: str,
    svc: ServicesDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PREVIEW_ROWS)] = DEFAULT_PREVIEW_ROWS,
) -> dict[str, Any]:
    """First rows of a table that exists in the source catalog (never raw SQL)."""
    conn = await get_connection_or_404(session, wid, cid)

    def read(c: Connector) -> tuple[SourceTable, list[tuple[Any, ...]]]:
        found = c.find_table(schema, table)  # NOT_FOUND unless it is in the catalog
        return found, list(c.preview(schema, table, limit))

    found, rows = await _with_connector(svc, conn, read)
    return {
        "schema": found.schema,
        "name": found.name,
        "columns": [c.name for c in found.columns],
        "rows": [[jsonable(v) for v in row] for row in rows],
        "limit": limit,
    }
