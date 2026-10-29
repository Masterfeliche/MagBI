from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from magbi.config import Settings
from magbi.connections import ConnectionService
from magbi.connectors.base import SourceColumn, SourceTable
from magbi.main import create_app
from magbi.metadata.models import Base
from magbi.services import Services
from tests.fakes import FakeConnector

PASSWORD = "Sup3r;Secret}pw"
CONN_CONFIG: dict[str, Any] = {
    "host": "erp.example.com",
    "database": "MSD",
    "authentication": "sql",
    "username": "bi",
    "password": PASSWORD,
}

ORDERS = SourceTable(
    schema="dbo",
    name="orders",
    estimated_rows=3,
    columns=[
        SourceColumn("id", "int", is_nullable=False, is_primary_key=True),
        SourceColumn("amount", "decimal(10,2)", precision=10, scale=2),
        SourceColumn("placed", "datetime2"),
        SourceColumn("blob", "varbinary(64)"),
        SourceColumn("shape", "geography"),
    ],
)
ORDER_ROWS: list[tuple[Any, ...]] = [
    (1, Decimal("9.50"), dt.datetime(2024, 5, 1, 10, 30), b"\x01\x02", "POINT (1 2)"),
    (2, None, None, None, None),
    (3, Decimal("0.01"), dt.datetime(2024, 5, 2), b"\xff" * 100, "POINT (3 4)"),
]


@dataclass
class ApiEnv:
    client: TestClient
    fake: FakeConnector
    services: Services
    settings: Settings

    def workspace(self, name: str = "msd") -> str:
        r = self.client.post("/api/v1/workspaces", json={"name": name})
        assert r.status_code == 201, r.text
        return str(r.json()["id"])

    def connection(self, wid: str, name: str = "erp", **config: Any) -> str:
        body = {"name": name, "kind": "sqlserver", "config": {**CONN_CONFIG, **config}}
        r = self.client.post(f"/api/v1/workspaces/{wid}/connections", json=body)
        assert r.status_code == 201, r.text
        return str(r.json()["id"])


@pytest.fixture
def api(test_settings: Settings) -> Iterator[ApiEnv]:
    # Create the metadata schema up front (the app itself relies on Alembic).
    sync_url = test_settings.database_url.replace("+aiosqlite", "")
    engine = sa.create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    fake = FakeConnector([ORDERS], {"dbo.orders": ORDER_ROWS})
    with TestClient(create_app(test_settings)) as client:
        svc: Services = client.app.state.services  # type: ignore[attr-defined]
        service = ConnectionService(svc.vault, connectors={"sqlserver": lambda: fake})
        svc.connections = service
        svc.refresh.connections = service
        yield ApiEnv(client, fake, svc, test_settings)
