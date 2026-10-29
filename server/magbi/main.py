"""FastAPI application entry point."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from magbi import __version__
from magbi.config import Settings
from magbi.config import settings as default_settings
from magbi.metadata.db import check_connection, create_engine, create_session_factory
from magbi.storage.credentials import CredentialVault
from magbi.storage.duckdb_store import DuckDBStore

log = logging.getLogger("magbi")


@dataclass
class Services:
    """Long-lived dependencies, created at startup and kept on ``app.state``."""

    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    store: DuckDBStore
    vault: CredentialVault | None


def ensure_data_dir(path: Path) -> None:
    """Create the dataset directory and prove it is writable."""
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=path):
        pass


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or default_settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ensure_data_dir(cfg.duckdb_data_dir)  # fail fast: nothing works without it
        engine = create_engine(cfg.database_url)
        try:
            await check_connection(engine)
        except Exception as exc:  # noqa: BLE001 - keep serving; /health/ready reports it
            log.warning(
                "metadata database unreachable at startup: %s", type(exc).__name__
            )
        app.state.services = Services(
            settings=cfg,
            engine=engine,
            sessions=create_session_factory(engine),
            store=DuckDBStore(cfg.duckdb_data_dir, cfg.duckdb_archive_versions),
            vault=(
                CredentialVault.from_encoded_key(cfg.credential_key)
                if cfg.credential_key
                else None
            ),
        )
        if cfg.credential_key == "":
            log.warning("MAGBI_CREDENTIAL_KEY is not set; connection secrets disabled")
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="MagBI",
        version=__version__,
        description="General-purpose BI engine — connect, model, visualise, embed.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready(request: Request, response: Response) -> dict[str, object]:
        svc: Services = request.app.state.services
        checks: dict[str, str] = {}
        try:
            await check_connection(svc.engine)
            checks["database"] = "ok"
        except Exception as exc:  # noqa: BLE001 - any driver error means "not ready"
            checks["database"] = f"unavailable ({type(exc).__name__})"
        try:
            ensure_data_dir(svc.settings.duckdb_data_dir)
            checks["data_dir"] = "ok"
        except OSError as exc:
            checks["data_dir"] = f"unavailable ({type(exc).__name__})"

        ok = all(v == "ok" for v in checks.values())
        if not ok:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "ready" if ok else "not_ready", "checks": checks}

    return app


app = create_app()
