"""Shared pytest fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from magbi.config import Settings
from magbi.main import create_app
from magbi.storage.credentials import generate_key


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'meta.db'}",
        duckdb_data_dir=tmp_path / "datasets",
        credential_key=generate_key(),
        jwt_secret="test-secret-test-secret-test-secret",
        insecure_admin_api=True,
    )


@pytest.fixture
def client(test_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(test_settings)) as c:
        yield c
