import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from magbi.config import Settings
from magbi.main import Services, create_app, ensure_data_dir


def test_health_returns_ok(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "version": "0.1.0"}


def test_live(client: TestClient) -> None:
    assert client.get("/health/live").json() == {"status": "ok"}


def test_ready_ok(client: TestClient, test_settings: Settings) -> None:
    res = client.get("/health/ready")
    assert res.status_code == 200
    assert res.json() == {
        "status": "ready",
        "checks": {"database": "ok", "data_dir": "ok"},
    }
    assert test_settings.duckdb_data_dir.is_dir()


def test_startup_wires_services(client: TestClient) -> None:
    svc: Services = client.app.state.services  # type: ignore[attr-defined]
    assert svc.vault is not None
    assert svc.store.root == svc.settings.duckdb_data_dir


def test_ready_reports_database_down(test_settings: Settings, tmp_path: Path) -> None:
    bad = test_settings.model_copy(
        update={
            "database_url": f"sqlite+aiosqlite:///{tmp_path / 'no' / 'dir' / 'x.db'}"
        }
    )
    with TestClient(create_app(bad)) as c:
        res = c.get("/health/ready")
        assert res.status_code == 503
        body = res.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["database"].startswith("unavailable")
        assert body["checks"]["data_dir"] == "ok"
        assert str(tmp_path) not in res.text  # no path/URL leakage
        assert c.get("/health").status_code == 200  # liveness unaffected


def test_ready_reports_data_dir_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_: Path) -> None:
        raise PermissionError("read-only")

    monkeypatch.setattr("magbi.main.ensure_data_dir", boom)
    res = client.get("/health/ready")
    assert res.status_code == 503
    assert res.json()["checks"]["data_dir"] == "unavailable (PermissionError)"
    assert res.json()["checks"]["database"] == "ok"


def test_startup_fails_when_data_dir_unwritable(
    test_settings: Settings, tmp_path: Path
) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    bad = test_settings.model_copy(update={"duckdb_data_dir": blocker / "datasets"})
    with pytest.raises(OSError), TestClient(create_app(bad)):
        pass


def test_startup_warns_when_database_down(
    test_settings: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bad = test_settings.model_copy(
        update={"database_url": f"sqlite+aiosqlite:///{tmp_path / 'no' / 'x.db'}"}
    )
    with caplog.at_level(logging.WARNING, logger="magbi"), TestClient(create_app(bad)):
        pass
    assert "metadata database unreachable" in caplog.text


def test_ensure_data_dir_creates_nested(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b"
    ensure_data_dir(target)
    assert target.is_dir()


def test_app_has_no_credential_vault_without_key(test_settings: Settings) -> None:
    # environment must be dev to allow an empty key
    dev = Settings(
        environment="dev",
        database_url=test_settings.database_url,
        duckdb_data_dir=test_settings.duckdb_data_dir,
    )
    with TestClient(create_app(dev)) as c:
        assert c.app.state.services.vault is None  # type: ignore[attr-defined]
