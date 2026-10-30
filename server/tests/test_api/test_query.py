import duckdb

from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"


def _definition() -> dict[str, object]:
    return {
        "tables": [
            {
                "name": "Sales",
                "columns": [{"name": "Amount", "data_type": "integer"}],
                "measures": [{"name": "Revenue", "expression": "SUM(Sales[Amount])"}],
            }
        ]
    }


def test_a_query_returns_rows_and_rejects_a_bad_field(api: ApiEnv) -> None:
    client = api.client
    wid = api.workspace()
    created = client.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "d"}).json()
    did = created["id"]
    url = f"{V1}/workspaces/{wid}/datasets/{did}/query"
    saved = client.put(
        f"{V1}/workspaces/{wid}/datasets/{did}/definition",
        json={"model_version": 1, "definition": _definition()},
    )
    assert saved.status_code == 200, saved.text
    missing = client.post(
        url,
        json={
            "query": {"select": [{"measure": {"table": "Sales", "measure": "Revenue"}}]}
        },
    )
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "DATA_NOT_READY"

    path = api.services.store.live_path(did)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute('CREATE TABLE "Sales" ("Amount" INTEGER)')
    con.execute('INSERT INTO "Sales" VALUES (4), (6)')
    con.close()

    ok = client.post(
        url,
        json={
            "query": {"select": [{"measure": {"table": "Sales", "measure": "Revenue"}}]}
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["rows"] == [[10]]
    assert ok.json()["rowCount"] == 1

    bad = client.post(
        url,
        json={"query": {"select": [{"column": {"table": "Sales", "column": "Nope"}}]}},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "UNKNOWN_COLUMN"
    assert (
        client.get(f"{V1}/workspaces/{wid}/datasets/{did}").json()["model_version"] == 2
    )


def test_a_missing_dataset_is_not_found(api: ApiEnv) -> None:
    client = api.client
    wid = api.workspace()
    missing = client.post(
        f"{V1}/workspaces/{wid}/datasets/00000000-0000-0000-0000-000000000000/query",
        json={
            "query": {"select": [{"column": {"table": "Sales", "column": "Amount"}}]}
        },
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "DATASET_NOT_FOUND"
