import duckdb

from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"


def test_preview_returns_rows_and_the_fold_boundary(api: ApiEnv) -> None:
    client = api.client
    wid = api.workspace()
    created = client.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "d"}).json()
    did = created["id"]
    saved = client.put(
        f"{V1}/workspaces/{wid}/datasets/{did}/definition",
        json={
            "model_version": 1,
            "definition": {
                "tables": [
                    {
                        "name": "Sales",
                        "columns": [
                            {"name": "Status", "data_type": "string"},
                            {"name": "Amount", "data_type": "integer"},
                        ],
                    }
                ]
            },
        },
    )
    assert saved.status_code == 200, saved.text
    url = f"{V1}/workspaces/{wid}/datasets/{did}/transforms/preview"
    waiting = client.post(
        url,
        json={
            "table": "Sales",
            "steps": [
                {
                    "type": "filterRows",
                    "column": "Status",
                    "operator": "eq",
                    "value": "Open",
                }
            ],
        },
    )
    assert waiting.status_code == 409
    assert waiting.json()["error"]["code"] == "DATA_NOT_READY"

    path = api.services.store.live_path(did)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute('CREATE TABLE "Sales" ("Status" VARCHAR, "Amount" INTEGER)')
    con.execute("INSERT INTO \"Sales\" VALUES ('Open', 4), ('Done', 9)")
    con.close()

    shown = client.post(
        url,
        json={
            "table": "Sales",
            "steps": [
                {
                    "type": "filterRows",
                    "column": "Status",
                    "operator": "eq",
                    "value": "Open",
                },
                {"type": "fillDown", "columns": ["Status"]},
            ],
        },
    )
    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert body["rows"] == [["Open", 4]]
    assert body["foldBoundary"] == 1
    assert body["foldedStepCount"] == 1
    assert "SELECT" in body["sql"]

    bad = client.post(url, json={"table": "Sales", "steps": [{"type": "nope"}]})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "TRANSFORM_STEP"


def test_a_missing_dataset_preview_is_not_found(api: ApiEnv) -> None:
    client = api.client
    wid = api.workspace()
    missing = client.post(
        f"{V1}/workspaces/{wid}/datasets/00000000-0000-0000-0000-000000000000/transforms/preview",
        json={"table": "Sales", "steps": []},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "DATASET_NOT_FOUND"
