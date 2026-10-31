"""Editing saves a draft; viewers and embeds see the published report until Publish."""

from __future__ import annotations

from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"


def _setup(api: ApiEnv) -> tuple[str, str, dict[str, str]]:
    wid = api.workspace()
    did = api.client.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "d"}).json()["id"]
    rid = api.client.post(
        f"{V1}/workspaces/{wid}/reports",
        json={"name": "Live", "dataset_id": did, "definition": {"pages": ["published"]}, "is_published": True},
    ).json()["id"]
    api.client.post(f"{V1}/admin/users", json={"email": "v@example.com", "name": "v", "password": "pass-word-1"})
    api.client.post(f"{V1}/workspaces/{wid}/members", json={"email": "v@example.com", "role": "viewer"})
    token = api.client.post(f"{V1}/auth/login", json={"email": "v@example.com", "password": "pass-word-1"}).json()["token"]
    return wid, rid, {"Authorization": f"Bearer {token}"}


def test_a_draft_never_reaches_viewers_until_published(api: ApiEnv) -> None:
    wid, rid, viewer = _setup(api)
    url = f"{V1}/workspaces/{wid}/reports/{rid}"
    before = api.client.get(url).json()["updated_at"]

    saved = api.client.put(url, json={"draft": {"pages": ["draft"]}})
    assert saved.status_code == 200, saved.text
    editor_view = api.client.get(url).json()
    assert editor_view["definition"] == {"pages": ["published"]}
    assert editor_view["draft"] == {"pages": ["draft"]}
    assert editor_view["has_draft"] is True
    assert editor_view["updated_at"] == before

    seen = api.client.get(url, headers=viewer).json()
    assert seen["definition"] == {"pages": ["published"]}
    assert seen["draft"] is None and seen["has_draft"] is True
    assert api.client.get(f"{V1}/workspaces/{wid}/reports", headers=viewer).json()[0]["draft"] is None

    published = api.client.put(url, json={"definition": {"pages": ["draft"]}, "is_published": True}).json()
    assert published["definition"] == {"pages": ["draft"]}
    assert published["has_draft"] is False and published["draft"] is None
    assert api.client.get(url, headers=viewer).json()["definition"] == {"pages": ["draft"]}


def test_a_draft_can_be_discarded_and_not_mixed_with_publish(api: ApiEnv) -> None:
    wid, rid, viewer = _setup(api)
    url = f"{V1}/workspaces/{wid}/reports/{rid}"
    api.client.put(url, json={"draft": {"pages": ["draft"]}})
    both = api.client.put(url, json={"draft": {"pages": ["x"]}, "definition": {"pages": ["y"]}})
    assert both.status_code == 422
    discarded = api.client.put(url, json={"discard_draft": True}).json()
    assert discarded["has_draft"] is False
    assert discarded["definition"] == {"pages": ["published"]}
    # A viewer cannot save a draft either.
    assert api.client.put(url, headers=viewer, json={"draft": {"pages": ["z"]}}).status_code == 403
