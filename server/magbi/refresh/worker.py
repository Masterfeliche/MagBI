"""Celery entry point for the refresh runner.

The API still starts ``run_refresh`` in-process. A worker process runs this
task with the same coroutine. Tests call ``run_refresh`` directly.
"""

from __future__ import annotations

import asyncio
import uuid

from celery import Celery

from magbi.config import settings

celery_app = Celery("magbi", broker=settings.redis_url)


@celery_app.task(name="magbi.refresh_dataset")  # type: ignore[untyped-decorator]
def refresh_dataset(refresh_id: str) -> None:
    """Run one queued refresh to completion."""
    asyncio.run(_execute(refresh_id))


async def _execute(refresh_id: str) -> None:
    from magbi.connections import ConnectionService, parse_allowed_hosts
    from magbi.metadata.db import create_engine, create_session_factory
    from magbi.refresh.orchestrator import RefreshDeps, run_refresh
    from magbi.storage.credentials import CredentialVault
    from magbi.storage.duckdb_store import DuckDBStore

    cfg = settings
    engine = create_engine(cfg.database_url)
    vault = (
        CredentialVault.from_encoded_key(cfg.credential_key)
        if cfg.credential_key
        else None
    )
    deps = RefreshDeps(
        create_session_factory(engine),
        DuckDBStore(cfg.duckdb_data_dir, cfg.duckdb_archive_versions),
        ConnectionService(vault, parse_allowed_hosts(cfg.connector_allowed_hosts)),
        batch_size=cfg.import_batch_size,
    )
    try:
        await run_refresh(deps, uuid.UUID(refresh_id))
    finally:
        await engine.dispose()
