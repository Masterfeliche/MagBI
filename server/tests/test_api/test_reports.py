"""Report create and update store the definition and the published flag."""

from __future__ import annotations

from tests.test_api.conftest import ApiEnv


def test_publish_stores_definition(api: ApiEnv) -> None:
    wid = api.workspace()
    created_dataset = api.client.post(
        f"/api/v1/workspaces/{wid}/datasets", json={"name": "sales"}
    )
    assert created_dataset.status_code == 201, created_dataset.text
    did = created_dataset.json()["id"]
    definition = {"schemaVersion": "1", "pages": [{"name": "page-1"}]}

    created = api.client.post(
        f"/api/v1/workspaces/{wid}/reports",
        json={
            "name": "Board",
            "dataset_id": did,
            "definition": definition,
            "is_published": False,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["is_published"] is False
    assert body["definition"]["pages"][0]["name"] == "page-1"

    published = {
        "schemaVersion": "1",
        "pages": [{"name": "page-1", "visuals": [{"id": "card"}]}],
    }
    updated = api.client.put(
        f"/api/v1/workspaces/{wid}/reports/{body['id']}",
        json={"definition": published, "is_published": True},
    )
    assert updated.status_code == 200, updated.text
    saved = updated.json()
    assert saved["is_published"] is True
    assert saved["definition"]["pages"][0]["visuals"][0]["id"] == "card"
