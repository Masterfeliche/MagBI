"""Long-lived application dependencies, created at startup on ``app.state``."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from magbi.config import Settings
from magbi.connections import ConnectionService
from magbi.notify.mail import Mailer
from magbi.refresh.orchestrator import RefreshDeps
from magbi.storage.credentials import CredentialVault
from magbi.storage.duckdb_store import DuckDBStore


@dataclass
class Services:
    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    store: DuckDBStore
    vault: CredentialVault | None
    connections: ConnectionService
    refresh: RefreshDeps
    # Sends subscription and alert mail; None until SMTP is configured.
    mailer: Mailer | None = None
