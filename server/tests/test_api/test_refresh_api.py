from __future__ import annotations

import uuid
from typing import Any

import duckdb
import pytest

from magbi.connectors.errors import ConnectorError, ErrorCode
from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"


def make_dataset(api: ApiEnv, wid: str, with_spec: bool = True) -> str:
    body: dict[str, Any] = {"name": f"ds-{uuid.uuid4().hex[:6]}"}
    if with_spec:
        cid = api.connection(wid, name=f"c-{uuid.uuid4().hex[:6]}")
        body["import_spec"] = {
            "connection_id": cid,
            "tables": [{"schema": "dbo", "name": "orders", "target": "orders"}],
        }
    r = api.client.post(f"{V1}/workspaces/{wid}/datasets", json=body)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def test_refresh_end_to_end(api: ApiEnv) -> None:
    wid = api.workspace()
    did = make_dataset(api, wid)
    r = api.client.post(f"{V1}/workspaces/{wid}/datasets/{did}/refresh")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued" and uuid.UUID(body["refresh_id"])

    status = api.client.get(
        f"{V1}/workspaces/{wid}/datasets/{did}/refresh/{body['refresh_id']}"
    ).json()
    assert status["status"] == "succeeded", status
    assert status["version"] == 1 and status["error"] is None
    assert (
        status["result"]["total_rows"] == 3
        and status["result"]["tables"][0]["target"] == "orders"
    )
    assert status["started_at"] and status["finished_at"]

    ds = api.client.get(f"{V1}/workspaces/{wid}/datasets/{did}").json()
    assert ds["current_version"] == 1

    # the data is really in live.duckdb and readable with plain DuckDB SQL
    live = api.services.store.live_path(did)
    con = duckdb.connect(str(live), read_only=True)
    try:
        assert con.execute("SELECT id FROM orders ORDER BY id").fetchall() == [
            (1,),
            (2,),
            (3,),
        ]
    finally:
        con.close()


def test_second_refresh_creates_version_2_and_history(api: ApiEnv) -> None:
    wid = api.workspace()
    did = make_dataset(api, wid)
    base = f"{V1}/workspaces/{wid}/datasets/{did}/refresh"
    first = api.client.post(base).json()["refresh_id"]
    second = api.client.post(base).json()["refresh_id"]
    history = api.client.get(f"{base}/history").json()
    assert {h["id"] for h in history} == {first, second}
    assert sorted(h["version"] for h in history) == [1, 2]
    assert all(h["status"] == "succeeded" for h in history)
    assert len(api.client.get(f"{base}/history", params={"limit": 1}).json()) == 1
    assert api.client.get(f"{base}/history", params={"limit": 0}).status_code == 422


def test_failed_refresh_is_reported_and_retryable(api: ApiEnv) -> None:
    wid = api.workspace()
    did = make_dataset(api, wid)
    base = f"{V1}/workspaces/{wid}/datasets/{did}/refresh"
    api.fake.fail_connect = ConnectorError(ErrorCode.UNREACHABLE, "cannot reach host")
    jid = api.client.post(base).json()["refresh_id"]
    failed = api.client.get(f"{base}/{jid}").json()
    assert failed["status"] == "failed" and "UNREACHABLE" in failed["error"]
    assert (
        api.client.get(f"{V1}/workspaces/{wid}/datasets/{did}").json()[
            "current_version"
        ]
        == 0
    )

    api.fake.fail_connect = None  # source recovers
    ok = api.client.post(base).json()["refresh_id"]
    assert api.client.get(f"{base}/{ok}").json()["status"] == "succeeded"


def test_failure_message_never_contains_the_password(api: ApiEnv) -> None:
    from tests.test_api.conftest import PASSWORD

    wid = api.workspace()
    did = make_dataset(api, wid)
    api.fake.fail_connect = ConnectorError(
        ErrorCode.QUERY_FAILED, f"bad pwd={PASSWORD}"
    )
    base = f"{V1}/workspaces/{wid}/datasets/{did}/refresh"
    jid = api.client.post(base).json()["refresh_id"]
    r = api.client.get(f"{base}/{jid}")
    assert PASSWORD not in r.text and "***" in r.json()["error"]


def test_conflict_while_a_refresh_is_active(
    api: ApiEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def never_runs(*_a: Any, **_k: Any) -> None:  # leaves the refresh queued
        return None

    monkeypatch.setattr("magbi.api.refresh.run_refresh", never_runs)
    wid = api.workspace()
    did = make_dataset(api, wid)
    base = f"{V1}/workspaces/{wid}/datasets/{did}/refresh"
    first = api.client.post(base)
    assert first.status_code == 202
    second = api.client.post(base)
    assert second.status_code == 409
    err = second.json()["error"]
    assert (
        err["code"] == "REFRESH_IN_PROGRESS"
        and err["refresh_id"] == first.json()["refresh_id"]
    )
    assert (
        api.client.get(f"{base}/{first.json()['refresh_id']}").json()["status"]
        == "queued"
    )


def test_other_datasets_are_not_blocked(
    api: ApiEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def never_runs(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr("magbi.api.refresh.run_refresh", never_runs)
    wid = api.workspace()
    a, b = make_dataset(api, wid), make_dataset(api, wid)
    assert (
        api.client.post(f"{V1}/workspaces/{wid}/datasets/{a}/refresh").status_code
        == 202
    )
    assert (
        api.client.post(f"{V1}/workspaces/{wid}/datasets/{b}/refresh").status_code
        == 202
    )


def test_dataset_without_import_spec_cannot_refresh(api: ApiEnv) -> None:
    wid = api.workspace()
    did = make_dataset(api, wid, with_spec=False)
    r = api.client.post(f"{V1}/workspaces/{wid}/datasets/{did}/refresh")
    assert (
        r.status_code == 422 and r.json()["error"]["code"] == "DATASET_NOT_CONFIGURED"
    )
    assert (
        api.client.get(f"{V1}/workspaces/{wid}/datasets/{did}/refresh/history").json()
        == []
    )


def test_refresh_scoping_and_404s(api: ApiEnv) -> None:
    wa, wb = api.workspace("a"), api.workspace("b")
    da, db = make_dataset(api, wa), make_dataset(api, wb)
    jid = api.client.post(f"{V1}/workspaces/{wa}/datasets/{da}/refresh").json()[
        "refresh_id"
    ]

    assert (
        api.client.post(f"{V1}/workspaces/{wb}/datasets/{da}/refresh").status_code
        == 404
    )
    assert (
        api.client.get(f"{V1}/workspaces/{wb}/datasets/{da}/refresh/{jid}").status_code
        == 404
    )
    # a job id from another dataset must not be readable through this one
    assert (
        api.client.get(f"{V1}/workspaces/{wb}/datasets/{db}/refresh/{jid}").status_code
        == 404
    )
    assert (
        api.client.get(
            f"{V1}/workspaces/{wa}/datasets/{da}/refresh/{uuid.uuid4()}"
        ).status_code
        == 404
    )
    assert (
        api.client.get(f"{V1}/workspaces/{wa}/datasets/{da}/refresh/nope").status_code
        == 422
    )
    assert (
        api.client.post(
            f"{V1}/workspaces/{wa}/datasets/{uuid.uuid4()}/refresh"
        ).status_code
        == 404
    )


def test_api_never_returns_password_anywhere_in_refresh_flow(api: ApiEnv) -> None:
    from tests.test_api.conftest import PASSWORD

    wid = api.workspace()
    did = make_dataset(api, wid)
    base = f"{V1}/workspaces/{wid}/datasets/{did}"
    texts = [
        api.client.post(f"{base}/refresh").text,
        api.client.get(f"{base}/refresh/history").text,
        api.client.get(base).text,
        api.client.get(f"{V1}/workspaces/{wid}/connections").text,
    ]
    assert all(PASSWORD not in t for t in texts)
