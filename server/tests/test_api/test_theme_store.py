"""Saved organisation and workspace themes: checks, defaults, lock, versions and who may change them."""

from __future__ import annotations

import sqlalchemy as sa

from magbi.metadata.models import AuditLog
from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"
HEALTHY = {"name": "Teal brand", "definition": {"extends": "health", "text": {"accent": "#145F5E"}}}


def _user(api: ApiEnv, wid: str, email: str, role: str | None) -> dict[str, str]:
    created = api.client.post(f"{V1}/admin/users", json={"email": email, "name": email, "password": "pass-word-1"})
    assert created.status_code == 201, created.text
    if role:
        added = api.client.post(f"{V1}/workspaces/{wid}/members", json={"email": email, "role": role})
        assert added.status_code == 201, added.text
    token = api.client.post(f"{V1}/auth/login", json={"email": email, "password": "pass-word-1"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_a_workspace_theme_is_checked_versioned_and_listed(api: ApiEnv) -> None:
    wid = api.workspace()
    url = f"{V1}/workspaces/{wid}/themes"
    created = api.client.post(url, json={**HEALTHY, "isDefault": True})
    assert created.status_code == 201, created.text
    theme = created.json()
    assert (theme["scope"], theme["version"], theme["isDefault"], theme["locked"]) == ("workspace", 1, True, False)

    updated = api.client.put(f"{url}/{theme['id']}", json={**HEALTHY, "name": "Teal brand 2", "isDefault": True})
    assert updated.json()["version"] == 2
    listed = api.client.get(url).json()
    assert listed["organisation"] == []
    assert [item["name"] for item in listed["workspace"]] == ["Teal brand 2"]

    engine = sa.create_engine(api.settings.database_url.replace("+aiosqlite", ""))
    with engine.connect() as conn:
        actions = list(conn.scalars(sa.select(AuditLog.action).where(AuditLog.object_type == "theme").order_by(AuditLog.id)))
    engine.dispose()
    assert actions == ["theme_create", "theme_update"]

    assert api.client.delete(f"{url}/{theme['id']}").status_code == 204
    assert api.client.get(url).json()["workspace"] == []


def test_a_theme_that_fails_the_checks_is_refused_with_the_reasons(api: ApiEnv) -> None:
    wid = api.workspace()
    url = f"{V1}/workspaces/{wid}/themes"
    unreadable = api.client.post(url, json={"name": "Grey", "definition": {"text": {"muted": "#D0D0D0"}}})
    assert unreadable.status_code == 422
    body = unreadable.json()["error"]
    assert body["code"] == "THEME_FAILS_CHECKS"
    assert any("text.muted" in item for item in body["problems"])
    unknown = api.client.post(url, json={"name": "X", "definition": {"extends": "neon"}})
    assert unknown.json()["error"]["code"] == "THEME_BASE_UNKNOWN"
    locked = api.client.post(url, json={**HEALTHY, "isDefault": True, "locked": True})
    assert locked.json()["error"]["code"] == "THEME_LOCK_ORGANISATION_ONLY"


def test_only_one_default_per_scope(api: ApiEnv) -> None:
    wid = api.workspace()
    url = f"{V1}/workspaces/{wid}/themes"
    first = api.client.post(url, json={**HEALTHY, "isDefault": True}).json()
    api.client.post(url, json={**HEALTHY, "name": "Second", "isDefault": True})
    listed = api.client.get(url).json()["workspace"]
    assert [item["name"] for item in listed if item["isDefault"]] == ["Second"]
    assert any(item["id"] == first["id"] and not item["isDefault"] for item in listed)


def test_only_a_platform_admin_changes_the_organisation_theme(api: ApiEnv) -> None:
    wid = api.workspace()
    admin = _user(api, wid, "admin@example.com", "admin")
    body = {"name": "Brand", "definition": {"extends": "enterprise-light"}, "isDefault": True, "locked": True}
    refused = api.client.post(f"{V1}/organisation/themes", headers=admin, json=body)
    assert refused.status_code == 403
    saved = api.client.post(f"{V1}/organisation/themes", json=body)
    assert saved.status_code == 201, saved.text
    assert saved.json()["locked"] is True
    # Every signed-in user, and every workspace, sees it.
    assert [item["name"] for item in api.client.get(f"{V1}/organisation/themes", headers=admin).json()] == ["Brand"]
    assert api.client.get(f"{V1}/workspaces/{wid}/themes", headers=admin).json()["organisation"][0]["locked"] is True
    # A theme that is not the default cannot stay locked.
    relaxed = api.client.put(f"{V1}/organisation/themes/{saved.json()['id']}", json={**body, "isDefault": False})
    assert relaxed.json()["locked"] is False
    assert api.client.delete(f"{V1}/organisation/themes/{saved.json()['id']}", headers=admin).status_code == 403


def test_an_embed_token_reads_its_workspace_themes_only(api: ApiEnv) -> None:
    wid = api.workspace()
    other = api.workspace("other")
    did = api.client.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "d"}).json()["id"]
    rid = api.client.post(f"{V1}/workspaces/{wid}/reports", json={"name": "r", "dataset_id": did, "is_published": True}).json()["id"]
    secret = api.client.post(f"{V1}/admin/service-tokens", json={"workspaceId": wid, "name": "erp"}).json()["token"]
    issued = api.client.post(
        f"{V1}/embed/token",
        headers={"Authorization": f"Bearer {secret}"},
        json={"userEmail": "ada@example.com", "userName": "Ada", "reports": [rid], "datasets": [did]},
    )
    assert issued.status_code == 200, issued.text
    embed = {"Authorization": f"Bearer {issued.json()['token']}"}
    assert api.client.get(f"{V1}/workspaces/{wid}/themes", headers=embed).status_code == 200
    assert api.client.get(f"{V1}/workspaces/{other}/themes", headers=embed).status_code == 403
    assert api.client.post(f"{V1}/workspaces/{wid}/themes", headers=embed, json=HEALTHY).status_code == 403
