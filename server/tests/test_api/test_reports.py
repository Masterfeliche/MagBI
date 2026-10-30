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

    fetched = api.client.get(f"/api/v1/workspaces/{wid}/reports/{body['id']}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["name"] == "Board"
    assert fetched.json()["definition"]["pages"][0]["visuals"][0]["id"] == "card"
    assert fetched.json()["last_refreshed_at"] is None


def test_embed_token_cannot_read_another_or_unpublished_report(api: ApiEnv) -> None:
    client = api.client
    wid = api.workspace()
    did = client.post(
        f"/api/v1/workspaces/{wid}/datasets", json={"name": "sales"}
    ).json()["id"]
    published = client.post(
        f"/api/v1/workspaces/{wid}/reports",
        json={
            "name": "Live",
            "dataset_id": did,
            "definition": {"pages": []},
            "is_published": True,
        },
    ).json()
    draft = client.post(
        f"/api/v1/workspaces/{wid}/reports",
        json={
            "name": "Draft",
            "dataset_id": did,
            "definition": {"pages": []},
            "is_published": False,
        },
    ).json()
    secret = client.post(
        "/api/v1/admin/service-tokens",
        json={"workspaceId": wid, "name": "host"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {secret}"}
    unpublished = client.post(
        "/api/v1/embed/token",
        headers=headers,
        json={
            "userEmail": "ada@example.com",
            "userName": "Ada",
            "reports": [draft["id"]],
            "datasets": [did],
        },
    )
    assert unpublished.status_code == 422
    assert unpublished.json()["error"]["code"] == "REPORT_NOT_PUBLISHED"

    minted = client.post(
        "/api/v1/embed/token",
        headers=headers,
        json={
            "userEmail": "ada@example.com",
            "userName": "Ada",
            "reports": [published["id"]],
            "datasets": [did],
        },
    )
    assert minted.status_code == 200, minted.text
    embed_headers = {"Authorization": f"Bearer {minted.json()['token']}"}
    allowed = client.get(
        f"/api/v1/workspaces/{wid}/reports/{published['id']}",
        headers=embed_headers,
    )
    assert allowed.status_code == 200, allowed.text
    other = client.get(
        f"/api/v1/workspaces/{wid}/reports/{draft['id']}",
        headers=embed_headers,
    )
    assert other.status_code == 403
