"""API -> real SQL Server -> import -> live.duckdb, checked with plain DuckDB SQL."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import duckdb
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from magbi.config import Settings
from magbi.connectors.sqlserver import SqlServerConnector
from magbi.main import create_app
from magbi.metadata.models import Base
from magbi.services import Services

pytestmark = pytest.mark.integration
V1 = "/api/v1"


@pytest.fixture
def client(test_settings: Settings) -> Iterator[TestClient]:
    engine = sa.create_engine(test_settings.database_url.replace("+aiosqlite", ""))
    Base.metadata.create_all(engine)
    engine.dispose()
    with TestClient(create_app(test_settings)) as c:
        yield c


def test_import_through_the_api(
    client: TestClient, mssql_config: dict[str, Any], connector: SqlServerConnector
) -> None:
    svc: Services = client.app.state.services  # type: ignore[attr-defined]

    wid = client.post(f"{V1}/workspaces", json={"name": "e2e"}).json()["id"]
    test = client.post(
        f"{V1}/workspaces/{wid}/connections/test",
        json={"kind": "sqlserver", "config": mssql_config},
    ).json()
    assert test["success"], test

    cid = client.post(
        f"{V1}/workspaces/{wid}/connections",
        json={"name": "src", "kind": "sqlserver", "config": mssql_config},
    ).json()["id"]
    browse = f"{V1}/workspaces/{wid}/connections/{cid}"
    tables = client.get(f"{browse}/tables", params={"schema": "sales"}).json()["tables"]
    assert {t["name"] for t in tables} >= {"Order Lines", "big_lines"}
    preview = client.get(
        f"{browse}/tables/sales/Order Lines/preview", params={"limit": 3}
    ).json()
    assert len(preview["rows"]) == 3 and preview["columns"][0] == "Line ID"

    spec = {
        "connection_id": cid,
        "tables": [
            {"schema": "sales", "name": "Order Lines", "target": "order_lines"},
            {"schema": "dbo", "name": "all_types"},
            {"schema": "dbo", "name": "exotic_types"},
        ],
    }
    did = client.post(
        f"{V1}/workspaces/{wid}/datasets", json={"name": "d", "import_spec": spec}
    ).json()["id"]

    refresh = f"{V1}/workspaces/{wid}/datasets/{did}/refresh"
    jid = client.post(refresh)
    assert jid.status_code == 202
    status = client.get(f"{refresh}/{jid.json()['refresh_id']}").json()
    assert status["status"] == "succeeded", status
    assert status["result"]["total_rows"] == 200_000 + 3 + 2
    assert (
        client.get(f"{V1}/workspaces/{wid}/datasets/{did}").json()["current_version"]
        == 1
    )

    # Compare the imported file against the source of truth.
    source_rows = connector.get_row_count("sales", "Order Lines")
    source_sum = next(
        connector.execute_query(
            "SELECT SUM(CAST([Qty] AS bigint)) FROM sales.[Order Lines]"
        )
    )[0]
    live = duckdb.connect(str(svc.store.live_path(did)), read_only=True)
    try:
        assert live.execute(
            'SELECT count(*), sum("Qty") FROM order_lines'
        ).fetchone() == (source_rows, source_sum)
        assert live.execute(
            "SELECT c_nvarchar FROM all_types WHERE id = 3"
        ).fetchone() == ("日本語 😀 Ж",)
        assert live.execute(
            "SELECT c_hier FROM exotic_types WHERE id = 1"
        ).fetchone() == ("/1/2/",)
    finally:
        live.close()

    # A second refresh swaps in version 2 and archives version 1.
    jid2 = client.post(refresh).json()["refresh_id"]
    assert client.get(f"{refresh}/{jid2}").json()["version"] == 2
    assert svc.store.list_versions(did) == [1]
    history = client.get(f"{refresh}/history").json()
    assert [h["status"] for h in history] == ["succeeded", "succeeded"]


def test_wrong_credentials_fail_the_refresh_cleanly(
    client: TestClient, mssql_config_factory: Any
) -> None:
    svc: Services = client.app.state.services  # type: ignore[attr-defined]
    wid = client.post(f"{V1}/workspaces", json={"name": "bad"}).json()["id"]
    bad = mssql_config_factory(password="wrong-password-123")
    cid = client.post(
        f"{V1}/workspaces/{wid}/connections",
        json={"name": "src", "kind": "sqlserver", "config": bad},
    ).json()["id"]
    spec = {"connection_id": cid, "tables": [{"schema": "dbo", "name": "all_types"}]}
    did = client.post(
        f"{V1}/workspaces/{wid}/datasets", json={"name": "d", "import_spec": spec}
    ).json()["id"]
    jid = client.post(f"{V1}/workspaces/{wid}/datasets/{did}/refresh").json()[
        "refresh_id"
    ]
    job = client.get(f"{V1}/workspaces/{wid}/datasets/{did}/refresh/{jid}").json()
    assert job["status"] == "failed" and "AUTH_FAILED" in job["error"]
    assert "wrong-password-123" not in str(job)
    assert not svc.store.exists(did)
