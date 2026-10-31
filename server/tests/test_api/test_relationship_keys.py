"""Adding a relationship finds the unique one side by itself, as Power BI does."""

from __future__ import annotations

from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"


def _model(api: ApiEnv, regions: bytes) -> tuple[str, str]:
    wid = api.workspace()
    did = api.client.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "d"}).json()["id"]
    for name, body in (("Sales", b"Region,Amount\nNorth,5\nSouth,9\nNorth,1\n"), ("Region", regions)):
        up = api.client.post(
            f"{V1}/workspaces/{wid}/datasets/{did}/upload",
            files={"file": (f"{name}.csv", body, "text/csv")},
            data={"table_name": name},
        )
        assert up.status_code == 200, up.text
    return wid, did


def _add(api: ApiEnv, wid: str, did: str):  # type: ignore[no-untyped-def]
    version = api.client.get(f"{V1}/workspaces/{wid}/datasets/{did}/definition").json()["model_version"]
    return api.client.post(
        f"{V1}/workspaces/{wid}/datasets/{did}/definition/relationships",
        json={"model_version": version, "relationship": {
            "from": {"table": "Sales", "column": "Region"}, "to": {"table": "Region", "column": "Region"},
            "cardinality": "many-to-one"}},
    )


def test_a_unique_column_becomes_the_key(api: ApiEnv) -> None:
    wid, did = _model(api, b"Region,Manager\nNorth,Asha\nSouth,Baraka\n")
    added = _add(api, wid, did)
    assert added.status_code == 200, added.text
    region = next(t for t in added.json()["definition"]["tables"] if t["name"] == "Region")
    assert next(c for c in region["columns"] if c["name"] == "Region")["is_primary_key"] is True
    assert len(added.json()["definition"]["relationships"]) == 1


def test_a_repeating_column_is_refused_with_the_count(api: ApiEnv) -> None:
    wid, did = _model(api, b"Region,Manager\nNorth,Asha\nNorth,Juma\nSouth,Baraka\n")
    refused = _add(api, wid, did)
    assert refused.status_code == 422
    error = refused.json()["error"]
    assert error["code"] == "KEY_NOT_UNIQUE"
    assert "1 of its 3 rows repeat a value" in error["message"]
