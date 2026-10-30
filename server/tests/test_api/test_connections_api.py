from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from magbi.api.schemas import jsonable
from magbi.config import Settings
from magbi.connectors.errors import ConnectorError, ErrorCode
from magbi.main import create_app
from tests.test_api.conftest import CONN_CONFIG, PASSWORD, ApiEnv

V1 = "/api/v1"


def db_bytes(api: ApiEnv) -> bytes:
    path = api.settings.database_url.split("///", 1)[1]
    return Path(path).read_bytes()


# -- test (unsaved) -------------------------------------------------------------


def test_test_endpoint_success(api: ApiEnv) -> None:
    wid = api.workspace()
    r = api.client.post(
        f"{V1}/workspaces/{wid}/connections/test",
        json={"kind": "sqlserver", "config": CONN_CONFIG},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["server_version"] == "FakeDB 1.0"
    assert body["schemas"] == ["dbo"] and body["code"] is None
    assert PASSWORD not in r.text


def test_test_endpoint_reports_connect_failure_as_result(api: ApiEnv) -> None:
    api.fake.fail_connect = ConnectorError(ErrorCode.AUTH_FAILED, "login failed")
    wid = api.workspace()
    r = api.client.post(
        f"{V1}/workspaces/{wid}/connections/test",
        json={"kind": "sqlserver", "config": CONN_CONFIG},
    )
    assert r.status_code == 200
    assert r.json()["success"] is False and r.json()["code"] == "AUTH_FAILED"


def test_test_endpoint_rejects_bad_config_without_echoing_values(api: ApiEnv) -> None:
    wid = api.workspace()
    r = api.client.post(
        f"{V1}/workspaces/{wid}/connections/test",
        json={"kind": "sqlserver", "config": {**CONN_CONFIG, "port": PASSWORD}},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_CONFIG"
    assert PASSWORD not in r.text
    unsupported = api.client.post(
        f"{V1}/workspaces/{wid}/connections/test", json={"kind": "oracle", "config": {}}
    )
    assert (
        unsupported.status_code == 422
        and unsupported.json()["error"]["code"] == "UNSUPPORTED"
    )


def test_allow_list_blocks_ssrf_target(test_settings: Settings, api: ApiEnv) -> None:
    api.services.connections._allowed = ["erp.example.com"]
    wid = api.workspace()
    r = api.client.post(
        f"{V1}/workspaces/{wid}/connections/test",
        json={
            "kind": "sqlserver",
            "config": {**CONN_CONFIG, "host": "169.254.169.254"},
        },
    )
    assert r.status_code == 422 and "allowed host list" in r.json()["error"]["message"]
    assert api.fake.connected is False and api.fake.close_calls == 0  # never even tried


# -- CRUD ----------------------------------------------------------------------


def test_create_masks_and_encrypts_password(api: ApiEnv) -> None:
    wid = api.workspace()
    r = api.client.post(
        f"{V1}/workspaces/{wid}/connections",
        json={"name": "erp", "kind": "sqlserver", "config": CONN_CONFIG},
    )
    assert r.status_code == 201
    body = r.json()
    assert (
        body["config"]["password"] == "***"
        and body["config"]["host"] == "erp.example.com"
    )
    assert PASSWORD not in r.text and "secret_encrypted" not in body
    assert PASSWORD.encode() not in db_bytes(api)  # not stored in clear

    listed = api.client.get(f"{V1}/workspaces/{wid}/connections")
    got = api.client.get(f"{V1}/workspaces/{wid}/connections/{body['id']}")
    for resp in (listed, got):
        assert PASSWORD not in resp.text and "***" in resp.text


def test_connection_conflicts_and_scoping(api: ApiEnv) -> None:
    a, b = api.workspace("a"), api.workspace("b")
    cid = api.connection(a)
    dup = api.client.post(
        f"{V1}/workspaces/{a}/connections",
        json={"name": "erp", "kind": "sqlserver", "config": CONN_CONFIG},
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "CONNECTION_EXISTS"
    assert api.client.get(f"{V1}/workspaces/{b}/connections/{cid}").status_code == 404
    assert (
        api.client.get(f"{V1}/workspaces/{a}/connections/{uuid.uuid4()}").status_code
        == 404
    )
    assert api.client.get(f"{V1}/workspaces/{b}/connections").json() == []


def test_update_keeps_or_replaces_password(api: ApiEnv) -> None:
    wid = api.workspace()
    cid = api.connection(wid)
    url = f"{V1}/workspaces/{wid}/connections/{cid}"
    # a client that echoes back the masked value must not overwrite the secret
    r = api.client.put(
        url, json={"config": {**CONN_CONFIG, "password": "***", "database": "Other"}}
    )
    assert r.status_code == 200 and r.json()["config"]["database"] == "Other"
    assert (
        api.client.post(
            f"{V1}/workspaces/{wid}/connections/test",
            json={"kind": "sqlserver", "config": CONN_CONFIG},
        ).status_code
        == 200
    )
    api.client.get(f"{url}/schemas")
    assert api.fake.config is not None and api.fake.config["password"] == PASSWORD

    r = api.client.put(url, json={"config": {**CONN_CONFIG, "password": "new-pw"}})
    assert r.status_code == 200 and "new-pw" not in r.text
    api.client.get(f"{url}/schemas")
    assert api.fake.config["password"] == "new-pw"

    renamed = api.client.put(url, json={"name": "erp2"})
    assert (
        renamed.json()["name"] == "erp2"
        and renamed.json()["config"]["password"] == "***"
    )


def test_storing_password_without_credential_key_is_rejected(tmp_path: Path) -> None:
    cfg = Settings(
        environment="dev",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'm.db'}",
        duckdb_data_dir=tmp_path / "d",
        insecure_admin_api=True,
    )
    import sqlalchemy as sa

    from magbi.metadata.models import Base

    eng = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    Base.metadata.create_all(eng)
    eng.dispose()
    with TestClient(create_app(cfg)) as c:
        wid = c.post(f"{V1}/workspaces", json={"name": "w"}).json()["id"]
        r = c.post(
            f"{V1}/workspaces/{wid}/connections",
            json={"name": "x", "kind": "sqlserver", "config": CONN_CONFIG},
        )
        assert (
            r.status_code == 422
            and "MAGBI_CREDENTIAL_KEY" in r.json()["error"]["message"]
        )
        assert c.get(f"{V1}/workspaces/{wid}/connections").json() == []


# -- browsing --------------------------------------------------------------------


def test_list_schemas_and_tables_with_type_plans(api: ApiEnv) -> None:
    wid = api.workspace()
    cid = api.connection(wid)
    base = f"{V1}/workspaces/{wid}/connections/{cid}"
    assert api.client.get(f"{base}/schemas").json() == {"schemas": ["dbo"]}
    tables = api.client.get(f"{base}/tables", params={"schema": "dbo"}).json()["tables"]
    assert [t["name"] for t in tables] == ["orders"] and tables[0][
        "estimated_rows"
    ] == 3
    cols = {c["name"]: c for c in tables[0]["columns"]}
    assert cols["id"]["primary_key"] is True and cols["id"]["data_type"] == "integer"
    assert (
        cols["amount"]["data_type"] == "decimal" and cols["amount"]["warning"] is None
    )
    assert (
        cols["shape"]["data_type"] == "string" and cols["shape"]["warning"]
    )  # degraded, flagged
    assert api.fake.close_calls == 2  # connector closed after every call
    assert api.client.get(f"{base}/tables").status_code == 422  # schema is required


def test_preview_is_json_safe_and_capped(api: ApiEnv) -> None:
    wid = api.workspace()
    cid = api.connection(wid)
    base = f"{V1}/workspaces/{wid}/connections/{cid}/tables/dbo/orders/preview"
    body = api.client.get(base).json()
    assert body["columns"] == ["id", "amount", "placed", "blob", "shape"]
    assert body["rows"][0] == [
        1,
        "9.50",
        "2024-05-01T10:30:00",
        "0x0102",
        "POINT (1 2)",
    ]
    assert body["rows"][1] == [2, None, None, None, None]
    assert body["rows"][2][3] == "0x" + "ff" * 32 + "..."
    assert len(api.client.get(base, params={"limit": 2}).json()["rows"]) == 2
    assert api.client.get(base, params={"limit": 1001}).status_code == 422
    assert api.client.get(base, params={"limit": 0}).status_code == 422


def test_preview_only_reads_catalog_tables(api: ApiEnv) -> None:
    wid = api.workspace()
    cid = api.connection(wid)
    base = f"{V1}/workspaces/{wid}/connections/{cid}/tables"
    r = api.client.get(f"{base}/dbo/nope; DROP TABLE x/preview")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    assert api.fake.queries == []  # nothing was executed for an unknown table


def test_source_errors_map_to_gateway_statuses(api: ApiEnv) -> None:
    wid = api.workspace()
    cid = api.connection(wid)
    api.fake.fail_connect = ConnectorError(ErrorCode.UNREACHABLE, "cannot reach host")
    r = api.client.get(f"{V1}/workspaces/{wid}/connections/{cid}/schemas")
    assert r.status_code == 502 and r.json()["error"]["code"] == "UNREACHABLE"
    api.fake.fail_connect = ConnectorError(ErrorCode.TIMEOUT, "slow")
    assert (
        api.client.get(f"{V1}/workspaces/{wid}/connections/{cid}/schemas").status_code
        == 504
    )


def test_browse_unknown_connection_404(api: ApiEnv) -> None:
    wid = api.workspace()
    r = api.client.get(f"{V1}/workspaces/{wid}/connections/{uuid.uuid4()}/schemas")
    assert r.status_code == 404 and r.json()["error"]["code"] == "CONNECTION_NOT_FOUND"


def test_jsonable() -> None:
    import datetime as dt
    from decimal import Decimal

    assert jsonable(Decimal("1.50")) == "1.50"
    assert jsonable(dt.date(2024, 1, 2)) == "2024-01-02"
    assert jsonable(dt.time(1, 2, 3)) == "01:02:03"
    assert jsonable(float("nan")) == "nan" and jsonable(float("inf")) == "inf"
    assert jsonable(1.5) == 1.5 and jsonable(True) is True and jsonable(None) is None
    assert jsonable(b"\x00\x01") == "0x0001"
    assert jsonable(uuid.UUID(int=1)) == "00000000-0000-0000-0000-000000000001"
