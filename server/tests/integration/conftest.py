"""Fixtures for tests that need a real SQL Server (``pytest -m integration``).

Start one with ``docker compose --profile test up -d --wait mssql-test`` in
``deploy/``. When no server answers, every integration test is skipped.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from magbi.connectors.sqlserver import SqlServerConnector

SEED_FILE = Path(__file__).with_name("seed.sql")
DATABASE = "magbi_test"
SA_PASSWORD = os.environ.get("MAGBI_TEST_MSSQL_PASSWORD", "MagBI_Test_Passw0rd!")
RO_PASSWORD = "MagBI_Ro_Passw0rd!"


def _host() -> str:
    return os.environ.get("MAGBI_TEST_MSSQL_HOST", "localhost")


def _port() -> int:
    return int(os.environ.get("MAGBI_TEST_MSSQL_PORT", "14333"))


def _config(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "host": _host(),
        "port": _port(),
        "database": DATABASE,
        "authentication": "sql",
        "username": "sa",
        "password": SA_PASSWORD,
        "encrypt": True,
        "trust_server_certificate": True,  # the container uses a self-signed cert
        "connection_timeout": 5,
    }
    base.update(overrides)
    return base


def split_batches(script: str) -> list[str]:
    parts = re.split(r"^\s*GO\s*$", script, flags=re.MULTILINE | re.IGNORECASE)
    return [p.strip() for p in parts if p.strip()]


@pytest.fixture(scope="session")
def mssql_seeded() -> None:
    """Rebuild the ``magbi_test`` database, or skip the test when no server is up."""
    pyodbc = pytest.importorskip("pyodbc")
    cs = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={_host()},{_port()};DATABASE=master;UID=sa;PWD={{{SA_PASSWORD}}};"
        "Encrypt=yes;TrustServerCertificate=yes"
    )
    try:
        conn = pyodbc.connect(cs, autocommit=True, timeout=5)
    except pyodbc.Error as exc:
        pytest.skip(f"SQL Server test instance unavailable: {exc}")
    try:
        cursor = conn.cursor()
        for batch in split_batches(SEED_FILE.read_text(encoding="utf-8")):
            cursor.execute(batch)
            while cursor.nextset():
                pass
    finally:
        conn.close()


@pytest.fixture
def mssql_config(mssql_seeded: None) -> dict[str, Any]:
    return _config()


@pytest.fixture
def mssql_config_factory(mssql_seeded: None) -> Any:
    return _config


@pytest.fixture
def connector(mssql_config: dict[str, Any]) -> Iterator[SqlServerConnector]:
    c = SqlServerConnector()
    c.connect(mssql_config)
    try:
        yield c
    finally:
        c.close()
