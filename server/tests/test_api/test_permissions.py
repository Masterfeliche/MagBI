"""Every workspace route checks the caller's workspace role."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import pytest

from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"
ROLES = ("viewer", "editor", "admin")
RANK = {"none": 0, "viewer": 1, "editor": 2, "admin": 3}
# Query has its own check: a viewer may query, only an editor may set query roles.
SELF_CHECKED = {"/api/v1/workspaces/{wid}/datasets/{did}/query"}


@dataclass
class Team:
    wid: str
    tokens: dict[str, dict[str, str]]


def _login(api: ApiEnv, email: str) -> dict[str, str]:
    r = api.client.post(f"{V1}/auth/login", json={"email": email, "password": "pass-word-1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def team(api: ApiEnv) -> Team:
    wid = api.workspace("finance")
    for name in (*ROLES, "none"):
        email = f"{name}@example.com"
        created = api.client.post(
            f"{V1}/admin/users",
            json={"email": email, "name": name, "password": "pass-word-1"},
        )
        assert created.status_code == 201, created.text
        if name != "none":
            added = api.client.post(
                f"{V1}/workspaces/{wid}/members", json={"email": email, "role": name}
            )
            assert added.status_code == 201, added.text
    return Team(wid, {name: _login(api, f"{name}@example.com") for name in (*ROLES, "none")})


def _minimum(path: str, method: str) -> str:
    read = method in ("GET", "HEAD")
    if "/connections" in path:
        return "editor" if read else "admin"
    if path.startswith(f"{V1}/workspaces/{{wid}}/members") and not read:
        return "admin"
    return "viewer" if read else "editor"


def _workspace_routes(api: ApiEnv) -> list[tuple[str, str]]:
    paths = api.client.get("/openapi.json").json()["paths"]
    return [
        (path, method.upper())
        for path, operations in sorted(paths.items())
        if path.startswith(f"{V1}/workspaces/{{wid}}") and path not in SELF_CHECKED
        for method in sorted(operations)
        if method in ("get", "post", "put", "patch", "delete")
    ]


def _url(path: str, wid: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: wid if m.group(1) == "wid" else str(uuid.uuid4()), path)


def test_the_route_table_covers_every_kind_of_workspace_route(api: ApiEnv) -> None:
    routes = _workspace_routes(api)
    assert len(routes) >= 30, routes
    paths = {path for path, _ in routes}
    for fragment in ("/reports", "/datasets", "/upload", "/measures", "/relationships",
                     "/refresh", "/schedule", "/connections", "/transforms", "/members"):
        assert any(fragment in path for path in paths), fragment


@pytest.mark.parametrize("who", [*ROLES, "none"])
def test_each_role_gets_exactly_the_workspace_routes_it_should(
    api: ApiEnv, team: Team, who: str
) -> None:
    wrong = []
    for path, method in _workspace_routes(api):
        url = _url(path, team.wid)
        body = {"email": "nobody@example.com", "role": "viewer"} if "/members" in path else {}
        r = api.client.request(method, url, headers=team.tokens[who], json=body)
        allowed = RANK[who] >= RANK[_minimum(path, method)]
        if allowed and r.status_code == 403:
            wrong.append(f"{who} refused {method} {path}: {r.text}")
        if not allowed and r.status_code != 403:
            wrong.append(f"{who} reached {method} {path}: {r.status_code}")
    assert not wrong, "\n".join(wrong)


def test_a_viewer_cannot_change_a_report_but_an_editor_can(api: ApiEnv, team: Team) -> None:
    did = api.client.post(
        f"{V1}/workspaces/{team.wid}/datasets", json={"name": "gl"}
    ).json()["id"]
    rid = api.client.post(
        f"{V1}/workspaces/{team.wid}/reports", json={"name": "Ledger", "dataset_id": did}
    ).json()["id"]
    url = f"{V1}/workspaces/{team.wid}/reports/{rid}"
    assert api.client.get(url, headers=team.tokens["viewer"]).status_code == 200
    refused = api.client.put(url, headers=team.tokens["viewer"], json={"name": "x"})
    assert refused.status_code == 403
    assert api.client.get(url).json()["name"] == "Ledger"
    done = api.client.put(url, headers=team.tokens["editor"], json={"name": "Ledger v2"})
    assert done.status_code == 200, done.text


def test_users_see_only_their_workspaces_and_cannot_create_one(
    api: ApiEnv, team: Team
) -> None:
    api.workspace("secret")
    names = [w["name"] for w in api.client.get(f"{V1}/workspaces", headers=team.tokens["viewer"]).json()]
    assert names == ["finance"]
    assert api.client.get(f"{V1}/workspaces", headers=team.tokens["none"]).json() == []
    created = api.client.post(
        f"{V1}/workspaces", headers=team.tokens["admin"], json={"name": "mine"}
    )
    assert created.status_code == 403
