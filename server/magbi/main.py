"""FastAPI application entry point."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

from magbi import __version__
from magbi.api.errors import install_error_handlers
from magbi.api.router import api_router
from magbi.config import Settings
from magbi.config import settings as default_settings
from magbi.connections import ConnectionService, parse_allowed_hosts
from magbi.metadata.db import check_connection, create_engine, create_session_factory
from magbi.refresh.orchestrator import RefreshDeps, sweep_stale_refreshes
from magbi.services import Services
from magbi.storage.credentials import CredentialVault
from magbi.storage.duckdb_store import DuckDBStore

log = logging.getLogger("magbi")


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
        vault = (
            CredentialVault.from_encoded_key(cfg.credential_key)
            if cfg.credential_key
            else None
        )
        sessions = create_session_factory(engine)
        store = DuckDBStore(cfg.duckdb_data_dir, cfg.duckdb_archive_versions)
        connections = ConnectionService(
            vault, parse_allowed_hosts(cfg.connector_allowed_hosts)
        )
        app.state.services = Services(
            settings=cfg,
            engine=engine,
            sessions=sessions,
            store=store,
            vault=vault,
            connections=connections,
            refresh=RefreshDeps(sessions, store, connections, cfg.import_batch_size),
        )
        try:
            from magbi.auth.bootstrap import ensure_bootstrap_admin

            await ensure_bootstrap_admin(sessions, cfg)
        except Exception as exc:  # noqa: BLE001 - database may be down; /health/ready reports it
            log.warning("bootstrap admin skipped: %s", type(exc).__name__)
        try:
            await sweep_stale_refreshes(app.state.services.refresh)
        except Exception as exc:  # noqa: BLE001 - database may be down; /health/ready reports it
            log.warning("stale refresh sweep skipped: %s", type(exc).__name__)
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

    install_error_handlers(app)
    app.include_router(api_router)

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
