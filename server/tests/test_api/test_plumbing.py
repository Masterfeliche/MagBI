from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magbi.api.errors import ApiError, install_error_handlers
from magbi.config import Settings
from magbi.connectors.errors import ConnectorError, ErrorCode
from magbi.main import create_app
from magbi.refresh.importer import ImportPipelineError
from magbi.refresh.orchestrator import RefreshConflict
from magbi.storage.credentials import generate_key


def test_v1_is_mounted_and_old_prefixes_are_gone(client: TestClient) -> None:
    assert client.get("/api/v1/connection-kinds").json() == {"kinds": ["sqlserver"]}
    assert client.get("/api/connection-kinds").status_code == 404
    paths = {getattr(r, "path", "") for r in client.app.routes}  # type: ignore[attr-defined]
    assert not any(
        p.startswith(("/api/datasets", "/api/workspaces", "/api/refresh"))
        for p in paths
    )


def test_health_endpoints_are_not_gated(tmp_path: Path) -> None:
    cfg = Settings(
        environment="prod",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'm.db'}",
        duckdb_data_dir=tmp_path / "d",
        credential_key=generate_key(),
        jwt_secret="x" * 40,
    )
    with TestClient(create_app(cfg)) as c:
        assert c.get("/health").status_code == 200


def test_gate_closed_outside_dev_by_default(tmp_path: Path) -> None:
    cfg = Settings(
        environment="prod",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'm.db'}",
        duckdb_data_dir=tmp_path / "d",
        credential_key=generate_key(),
        jwt_secret="x" * 40,
    )
    with TestClient(create_app(cfg)) as c:
        r = c.get("/api/v1/connection-kinds")
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "ADMIN_API_DISABLED"
        assert "MAGBI_INSECURE_ADMIN_API" in r.json()["error"]["message"]


def test_gate_opens_with_explicit_opt_in(tmp_path: Path) -> None:
    cfg = Settings(
        environment="prod",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'm.db'}",
        duckdb_data_dir=tmp_path / "d",
        credential_key=generate_key(),
        jwt_secret="x" * 40,
        insecure_admin_api=True,
    )
    with TestClient(create_app(cfg)) as c:
        assert c.get("/api/v1/connection-kinds").status_code == 200


def test_gate_open_in_dev(tmp_path: Path) -> None:
    cfg = Settings(
        environment="dev",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'm.db'}",
        duckdb_data_dir=tmp_path / "d",
    )
    with TestClient(create_app(cfg)) as c:
        assert c.get("/api/v1/connection-kinds").status_code == 200


@pytest.fixture
def error_client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/connector/{code}")
    def connector(code: str) -> None:
        raise ConnectorError(ErrorCode(code), "boom")

    @app.get("/pipeline")
    def pipeline() -> None:
        raise ImportPipelineError("bad data")

    @app.get("/conflict")
    def conflict() -> None:
        raise RefreshConflict(uuid.UUID(int=7))

    @app.get("/api")
    def api() -> None:
        raise ApiError(418, "TEAPOT", "short and stout", hint="x")

    return TestClient(app)


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("INVALID_CONFIG", 422),
        ("UNSUPPORTED", 422),
        ("NOT_FOUND", 404),
        ("AUTH_FAILED", 400),
        ("UNREACHABLE", 502),
        ("TIMEOUT", 504),
        ("QUERY_FAILED", 502),
        ("NOT_CONNECTED", 500),
    ],
)
def test_connector_errors_map_to_json(
    error_client: TestClient, code: str, status: int
) -> None:
    r = error_client.get(f"/connector/{code}")
    assert r.status_code == status
    assert r.json() == {"error": {"code": code, "message": "boom"}}


def test_other_error_shapes(error_client: TestClient) -> None:
    r = error_client.get("/pipeline")
    assert r.status_code == 422 and r.json()["error"] == {
        "code": "IMPORT_FAILED",
        "message": "bad data",
    }
    r = error_client.get("/conflict")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "REFRESH_IN_PROGRESS"
    assert r.json()["error"]["refresh_id"] == str(uuid.UUID(int=7))
    r = error_client.get("/api")
    assert r.status_code == 418 and r.json()["error"]["hint"] == "x"


def test_every_error_code_has_a_status() -> None:
    from magbi.api.errors import CONNECTOR_STATUS

    assert set(CONNECTOR_STATUS) == set(ErrorCode)


def test_services_expose_connection_and_refresh_deps(client: TestClient) -> None:
    svc = client.app.state.services  # type: ignore[attr-defined]
    assert svc.refresh.store is svc.store
    assert svc.refresh.connections is svc.connections
    assert svc.refresh.batch_size == svc.settings.import_batch_size
