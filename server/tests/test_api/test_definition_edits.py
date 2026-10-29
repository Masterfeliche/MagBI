from __future__ import annotations

from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"


def _model() -> dict[str, object]:
    return {
        "tables": [
            {
                "name": "Invoices",
                "columns": [
                    {
                        "name": "id",
                        "data_type": "integer",
                        "is_nullable": False,
                        "is_primary_key": True,
                    },
                    {"name": "dept_id", "data_type": "integer"},
                    {"name": "placed", "data_type": "date"},
                ],
            },
            {
                "name": "Department",
                "columns": [
                    {
                        "name": "id",
                        "data_type": "integer",
                        "is_nullable": False,
                        "is_primary_key": True,
                    }
                ],
            },
        ]
    }


def _put(api: ApiEnv) -> tuple[str, str]:
    wid = api.workspace()
    created = api.client.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "d"})
    assert created.status_code == 201
    did = created.json()["id"]
    saved = api.client.put(
        f"{V1}/workspaces/{wid}/datasets/{did}/definition",
        json={"model_version": 1, "definition": _model()},
    )
    assert saved.status_code == 200, saved.text
    return wid, did


def test_measures_relationships_and_validate(api: ApiEnv) -> None:
    c = api.client
    wid, did = _put(api)
    base = f"{V1}/workspaces/{wid}/datasets/{did}/definition"

    added = c.post(
        f"{base}/measures",
        json={
            "model_version": 2,
            "table": "Invoices",
            "measure": {"name": "Total", "expression": "SUM(Invoices[amount])"},
        },
    )
    assert added.status_code == 200, added.text
    assert added.json()["definition"]["tables"][0]["measures"][0]["name"] == "Total"
    assert added.json()["model_version"] == 3

    changed = c.put(
        f"{base}/measures/total",
        json={
            "model_version": 3,
            "measure": {"name": "Total", "expression": "SUM(Invoices[id])"},
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["definition"]["tables"][0]["measures"][0]["expression"] == (
        "SUM(Invoices[id])"
    )

    missing_table = c.post(
        f"{base}/measures",
        json={
            "model_version": 4,
            "table": "Nope",
            "measure": {"name": "X", "expression": "1"},
        },
    )
    assert missing_table.status_code == 404
    assert missing_table.json()["error"]["code"] == "TABLE_NOT_FOUND"

    linked = c.post(
        f"{base}/relationships",
        json={
            "model_version": 4,
            "relationship": {
                "from": {"table": "Invoices", "column": "dept_id"},
                "to": {"table": "Department", "column": "id"},
                "cardinality": "many-to-one",
            },
        },
    )
    assert linked.status_code == 200, linked.text
    rel_id = linked.json()["definition"]["relationships"][0]["id"]
    assert linked.json()["model_version"] == 5

    illegal = c.post(
        f"{base}/relationships",
        json={
            "model_version": 5,
            "relationship": {
                "from": {"table": "Invoices", "column": "dept_id"},
                "to": {"table": "Department", "column": "id"},
                "cardinality": "many-to-many",
            },
        },
    )
    assert illegal.status_code == 422
    assert illegal.json()["error"]["code"] == "VALIDATION_FAILED"
    assert c.get(base).json()["model_version"] == 5

    dated = c.post(
        f"{base}/date-table",
        json={"model_version": 5, "start": "2024-01-01", "end": "2024-01-03"},
    )
    assert dated.status_code == 200, dated.text
    names = [t["name"] for t in dated.json()["definition"]["tables"]]
    assert "Date" in names
    assert dated.json()["definition"]["date_table"]["auto_generate"] is True
    assert any(
        r["to"]["table"] == "Date" and r["from"]["column"] == "placed"
        for r in dated.json()["definition"]["relationships"]
    )

    report = c.post(base + "/validate", json={"definition": {"tables": []}})
    assert report.status_code == 200
    assert report.json()["ok"] is True
    assert c.get(base).json()["model_version"] == 6  # validate does not save

    removed = c.delete(f"{base}/relationships/{rel_id}?model_version=6")
    assert removed.status_code == 200, removed.text
    assert removed.json()["definition"]["relationships"] == [] or all(
        r["id"] != rel_id for r in removed.json()["definition"]["relationships"]
    )
    gone = c.delete(f"{base}/measures/Total?model_version=7")
    assert gone.status_code == 200, gone.text
    assert gone.json()["definition"]["tables"][0]["measures"] == []


def test_date_table_needs_bounds_when_nothing_is_imported(api: ApiEnv) -> None:
    c = api.client
    wid, did = _put(api)
    r = c.post(
        f"{V1}/workspaces/{wid}/datasets/{did}/definition/date-table",
        json={"model_version": 2},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "DATE_BOUNDS_REQUIRED"
