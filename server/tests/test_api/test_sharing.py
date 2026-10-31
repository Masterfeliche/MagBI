"""Share a report with someone outside the workspace, and publish apps to an audience."""

from __future__ import annotations

from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"
SALES = b"Owner,Amount\nada@example.com,5\nada@example.com,1\nbo@example.com,9\n"


def _user(api: ApiEnv, email: str) -> dict[str, str]:
    api.client.post(f"{V1}/admin/users", json={"email": email, "name": email, "password": "pass-word-1"})
    token = api.client.post(f"{V1}/auth/login", json={"email": email, "password": "pass-word-1"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _setup(api: ApiEnv, roles: bool = False, workspace: str = "msd") -> tuple[str, str, str, str]:
    wid = api.workspace(workspace)
    did = api.client.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "d"}).json()["id"]
    up = api.client.post(f"{V1}/workspaces/{wid}/datasets/{did}/upload", files={"file": ("Sales.csv", SALES, "text/csv")}, data={"table_name": "Sales"})
    assert up.status_code == 200, up.text
    current = api.client.get(f"{V1}/workspaces/{wid}/datasets/{did}/definition").json()
    model = current["definition"]
    next(t for t in model["tables"] if t["name"] == "Sales")["measures"].append({"name": "Total", "expression": "SUM(Sales[Amount])"})
    if roles:
        model["roles"] = [{"name": "Mine", "table_filters": [{"table": "Sales", "expression": "[Owner] = USERPRINCIPALNAME()"}], "members": ["ada@example.com"]}]
    saved = api.client.put(f"{V1}/workspaces/{wid}/datasets/{did}/definition", json={"model_version": current["model_version"], "definition": model})
    assert saved.status_code == 200, saved.text
    rid = api.client.post(f"{V1}/workspaces/{wid}/reports", json={"name": "Sales", "dataset_id": did, "is_published": True}).json()["id"]
    other = api.client.post(f"{V1}/workspaces/{wid}/reports", json={"name": "Other", "dataset_id": did, "is_published": True}).json()["id"]
    return wid, did, rid, other


def _total(api: ApiEnv, wid: str, did: str, headers: dict[str, str]):  # type: ignore[no-untyped-def]
    return api.client.post(
        f"{V1}/workspaces/{wid}/datasets/{did}/query",
        headers=headers,
        json={"query": {"select": [{"measure": {"table": "Sales", "measure": "Total"}}]}},
    )


def test_a_shared_report_can_be_viewed_and_queried_until_revoked(api: ApiEnv) -> None:
    wid, did, rid, other = _setup(api)
    ada = _user(api, "ada@example.com")
    assert api.client.get(f"{V1}/workspaces/{wid}/reports/{rid}", headers=ada).status_code == 403
    assert _total(api, wid, did, ada).status_code == 403

    shared = api.client.post(f"{V1}/workspaces/{wid}/reports/{rid}/shares", json={"email": "ADA@example.com"})
    assert shared.status_code == 201, shared.text
    assert [s["email"] for s in api.client.get(f"{V1}/workspaces/{wid}/reports/{rid}/shares").json()] == ["ada@example.com"]
    seen = api.client.get(f"{V1}/workspaces/{wid}/reports/{rid}", headers=ada)
    assert seen.status_code == 200, seen.text
    assert _total(api, wid, did, ada).json()["rows"] == [[15]]
    assert [r["reportName"] for r in api.client.get(f"{V1}/me/shared", headers=ada).json()] == ["Sales"]

    # Only that report: not the workspace's other reports, its listing, or edits.
    assert api.client.get(f"{V1}/workspaces/{wid}/reports/{other}", headers=ada).status_code == 403
    assert api.client.get(f"{V1}/workspaces/{wid}/reports", headers=ada).status_code == 403
    assert api.client.get(f"{V1}/workspaces/{wid}/datasets/{did}/definition", headers=ada).status_code == 403
    assert api.client.put(f"{V1}/workspaces/{wid}/reports/{rid}", headers=ada, json={"name": "x"}).status_code == 403
    assert api.client.post(f"{V1}/workspaces/{wid}/reports/{rid}/shares", headers=ada, json={"email": "ada@example.com"}).status_code == 403

    user_id = shared.json()["userId"]
    assert api.client.delete(f"{V1}/workspaces/{wid}/reports/{rid}/shares/{user_id}").status_code == 204
    assert api.client.get(f"{V1}/workspaces/{wid}/reports/{rid}", headers=ada).status_code == 403
    assert _total(api, wid, did, ada).status_code == 403
    assert api.client.delete(f"{V1}/workspaces/{wid}/reports/{rid}/shares/{user_id}").status_code == 404


def test_sharing_with_an_unknown_email_says_so(api: ApiEnv) -> None:
    wid, _, rid, _ = _setup(api)
    refused = api.client.post(f"{V1}/workspaces/{wid}/reports/{rid}/shares", json={"email": "nobody@example.com"})
    assert refused.status_code == 404 and refused.json()["error"]["code"] == "USER_NOT_FOUND"


def test_row_level_security_still_applies_to_people_a_report_is_shared_with(api: ApiEnv) -> None:
    wid, did, rid, _ = _setup(api, roles=True)
    ada, bo = _user(api, "ada@example.com"), _user(api, "bo@example.com")
    for email in ("ada@example.com", "bo@example.com"):
        api.client.post(f"{V1}/workspaces/{wid}/reports/{rid}/shares", json={"email": email})
    assert _total(api, wid, did, ada).json()["rows"] == [[6]]
    refused = _total(api, wid, did, bo)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "RLS_NO_ROLE"


def test_a_published_app_grants_its_reports_to_its_audience(api: ApiEnv) -> None:
    wid, did, rid, other = _setup(api)
    bo = _user(api, "bo@example.com")
    made = api.client.post(f"{V1}/workspaces/{wid}/apps", json={"name": "Sales app", "reportIds": [rid], "audience": ["bo@example.com"]})
    assert made.status_code == 201, made.text
    app = made.json()
    assert app["reports"] == [{"id": rid, "name": "Sales"}] and app["audience"] == ["bo@example.com"]

    # Not until it is published.
    assert api.client.get(f"{V1}/me/apps", headers=bo).json() == []
    assert api.client.get(f"{V1}/apps/{app['id']}", headers=bo).status_code == 404
    assert api.client.get(f"{V1}/workspaces/{wid}/reports/{rid}", headers=bo).status_code == 403

    body = {"name": "Sales app", "reportIds": [rid], "audience": ["bo@example.com"], "isPublished": True}
    assert api.client.put(f"{V1}/workspaces/{wid}/apps/{app['id']}", json=body).status_code == 200
    mine = api.client.get(f"{V1}/me/apps", headers=bo).json()
    assert [a["name"] for a in mine] == ["Sales app"]
    seen = api.client.get(f"{V1}/apps/{app['id']}", headers=bo).json()
    assert seen["reports"] == [{"id": rid, "name": "Sales"}] and seen["audience"] == []
    assert api.client.get(f"{V1}/workspaces/{wid}/reports/{rid}", headers=bo).status_code == 200
    assert api.client.get(f"{V1}/workspaces/{wid}/reports/{other}", headers=bo).status_code == 403
    assert _total(api, wid, did, bo).json()["rows"] == [[15]]
    assert api.client.get(f"{V1}/workspaces/{wid}/themes", headers=bo).status_code == 200

    # Leaving the audience ends access.
    body["audience"] = []
    assert api.client.put(f"{V1}/workspaces/{wid}/apps/{app['id']}", json=body).status_code == 200
    assert api.client.get(f"{V1}/workspaces/{wid}/reports/{rid}", headers=bo).status_code == 403
    assert api.client.delete(f"{V1}/workspaces/{wid}/apps/{app['id']}").status_code == 204
    assert api.client.get(f"{V1}/workspaces/{wid}/apps").json() == []


def test_an_app_takes_only_this_workspaces_reports(api: ApiEnv) -> None:
    wid, *_ = _setup(api)
    _, _, foreign, _ = _setup(api, workspace="other")
    refused = api.client.post(f"{V1}/workspaces/{wid}/apps", json={"name": "x", "reportIds": [foreign]})
    assert refused.status_code == 404
