from __future__ import annotations

import uuid

import pytest

from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"


def test_workspace_create_list_get(api: ApiEnv) -> None:
    c = api.client
    r = c.post(f"{V1}/workspaces", json={"name": "  MSD  ", "description": "fleet"})
    assert r.status_code == 201
    ws = r.json()
    assert ws["name"] == "MSD" and ws["description"] == "fleet"
    assert c.get(f"{V1}/workspaces").json()[0]["id"] == ws["id"]
    assert c.get(f"{V1}/workspaces/{ws['id']}").json()["name"] == "MSD"


def test_workspace_errors(api: ApiEnv) -> None:
    c = api.client
    api.workspace("a")
    dup = c.post(f"{V1}/workspaces", json={"name": "a"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "WORKSPACE_EXISTS"
    missing = c.get(f"{V1}/workspaces/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "WORKSPACE_NOT_FOUND"
    assert c.get(f"{V1}/workspaces/not-a-uuid").status_code == 422
    assert c.post(f"{V1}/workspaces", json={"name": ""}).status_code == 422


def test_dataset_crud_without_spec(api: ApiEnv) -> None:
    c = api.client
    wid = api.workspace()
    r = c.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "fleet"})
    assert r.status_code == 201
    ds = r.json()
    assert (
        ds["import_spec"] is None
        and ds["current_version"] == 0
        and ds["mode"] == "import"
    )
    assert [d["id"] for d in c.get(f"{V1}/workspaces/{wid}/datasets").json()] == [
        ds["id"]
    ]
    assert c.get(f"{V1}/workspaces/{wid}/datasets/{ds['id']}").json()["name"] == "fleet"
    dup = c.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "fleet"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DATASET_EXISTS"


def test_dataset_with_import_spec_normalises_targets(api: ApiEnv) -> None:
    c = api.client
    wid = api.workspace()
    cid = api.connection(wid)
    spec = {
        "connection_id": cid,
        "tables": [
            {"schema": "dbo", "name": "orders"},
            {"schema": "sales", "name": "x", "target": "lines"},
        ],
    }
    r = c.post(
        f"{V1}/workspaces/{wid}/datasets", json={"name": "d", "import_spec": spec}
    )
    assert r.status_code == 201, r.text
    assert r.json()["import_spec"] == {
        "connection_id": cid,
        "tables": [
            {"schema": "dbo", "name": "orders", "target": "orders"},
            {"schema": "sales", "name": "x", "target": "lines"},
        ],
    }


@pytest.mark.parametrize(
    "tables",
    [
        [
            {"schema": "dbo", "name": "a"},
            {"schema": "dbo", "name": "A"},
        ],  # duplicate targets
        [{"schema": "dbo", "name": "a", "target": "x" * 129}],
        [],
    ],
)
def test_dataset_invalid_import_specs(
    api: ApiEnv, tables: list[dict[str, str]]
) -> None:
    wid = api.workspace()
    cid = api.connection(wid)
    r = api.client.post(
        f"{V1}/workspaces/{wid}/datasets",
        json={"name": "d", "import_spec": {"connection_id": cid, "tables": tables}},
    )
    assert r.status_code == 422


def test_dataset_connection_must_belong_to_workspace(api: ApiEnv) -> None:
    other = api.workspace("other")
    foreign = api.connection(other)
    wid = api.workspace("mine")
    r = api.client.post(
        f"{V1}/workspaces/{wid}/datasets",
        json={
            "name": "d",
            "import_spec": {
                "connection_id": foreign,
                "tables": [{"schema": "dbo", "name": "t"}],
            },
        },
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "CONNECTION_NOT_FOUND"
    ghost = api.client.post(
        f"{V1}/workspaces/{wid}/datasets",
        json={
            "name": "d",
            "import_spec": {
                "connection_id": str(uuid.uuid4()),
                "tables": [{"schema": "dbo", "name": "t"}],
            },
        },
    )
    assert ghost.status_code == 422


def test_dataset_is_scoped_to_its_workspace(api: ApiEnv) -> None:
    a, b = api.workspace("a"), api.workspace("b")
    ds = api.client.post(f"{V1}/workspaces/{a}/datasets", json={"name": "d"}).json()
    assert api.client.get(f"{V1}/workspaces/{b}/datasets/{ds['id']}").status_code == 404
    assert api.client.get(f"{V1}/workspaces/{b}/datasets").json() == []
    assert api.client.get(f"{V1}/workspaces/{uuid.uuid4()}/datasets").status_code == 404
    assert (
        api.client.post(
            f"{V1}/workspaces/{uuid.uuid4()}/datasets", json={"name": "x"}
        ).status_code
        == 404
    )


def test_dataset_update(api: ApiEnv) -> None:
    c = api.client
    wid = api.workspace()
    cid = api.connection(wid)
    first = c.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "d1"}).json()
    c.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "d2"})
    url = f"{V1}/workspaces/{wid}/datasets/{first['id']}"
    r = c.put(
        url,
        json={
            "name": "renamed",
            "import_spec": {
                "connection_id": cid,
                "tables": [{"schema": "dbo", "name": "orders"}],
            },
        },
    )
    assert r.status_code == 200 and r.json()["name"] == "renamed"
    assert r.json()["import_spec"]["tables"][0]["target"] == "orders"
    clash = c.put(url, json={"name": "d2"})
    assert clash.status_code == 409
    assert c.get(url).json()["name"] == "renamed"  # failed update changed nothing
    assert (
        c.put(f"{V1}/workspaces/{wid}/datasets/{uuid.uuid4()}", json={}).status_code
        == 404
    )
