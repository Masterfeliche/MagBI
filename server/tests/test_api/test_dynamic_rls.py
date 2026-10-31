"""Per-user row-level security, as in Power BI: role members, USERPRINCIPALNAME(), editors see all."""

from __future__ import annotations

from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"
SALES = b"Owner,Amount\nada@example.com,5\nada@example.com,1\nbo@example.com,9\n"


def _login(api: ApiEnv, wid: str, email: str, role: str) -> dict[str, str]:
    api.client.post(f"{V1}/admin/users", json={"email": email, "name": email, "password": "pass-word-1"})
    api.client.post(f"{V1}/workspaces/{wid}/members", json={"email": email, "role": role})
    token = api.client.post(f"{V1}/auth/login", json={"email": email, "password": "pass-word-1"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _total(api: ApiEnv, wid: str, did: str, headers: dict[str, str]):  # type: ignore[no-untyped-def]
    return api.client.post(
        f"{V1}/workspaces/{wid}/datasets/{did}/query",
        headers=headers,
        json={"query": {"select": [{"measure": {"table": "Sales", "measure": "Total"}}]}},
    )


def test_each_viewer_sees_only_their_rows_and_editors_see_all(api: ApiEnv) -> None:
    wid = api.workspace()
    did = api.client.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "d"}).json()["id"]
    up = api.client.post(f"{V1}/workspaces/{wid}/datasets/{did}/upload", files={"file": ("Sales.csv", SALES, "text/csv")}, data={"table_name": "Sales"})
    assert up.status_code == 200, up.text
    current = api.client.get(f"{V1}/workspaces/{wid}/datasets/{did}/definition").json()
    model = current["definition"]
    next(t for t in model["tables"] if t["name"] == "Sales")["measures"].append({"name": "Total", "expression": "SUM(Sales[Amount])"})
    model["roles"] = [{
        "name": "Mine",
        "table_filters": [{"table": "Sales", "expression": "[Owner] = USERPRINCIPALNAME()"}],
        "members": ["ADA@example.com", "bo@example.com"],
    }]
    saved = api.client.put(f"{V1}/workspaces/{wid}/datasets/{did}/definition", json={"model_version": current["model_version"], "definition": model})
    assert saved.status_code == 200, saved.text
    assert saved.json()["definition"]["roles"][0]["members"] == ["ada@example.com", "bo@example.com"]

    ada = _login(api, wid, "ada@example.com", "viewer")
    bo = _login(api, wid, "bo@example.com", "viewer")
    cy = _login(api, wid, "cy@example.com", "viewer")
    ed = _login(api, wid, "ed@example.com", "editor")
    first = _total(api, wid, did, ada)
    assert first.status_code == 200, first.text
    assert first.json()["rows"] == [[6]]
    assert _total(api, wid, did, bo).json()["rows"] == [[9]]
    refused = _total(api, wid, did, cy)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "RLS_NO_ROLE"
    assert _total(api, wid, did, ed).json()["rows"] == [[15]]

    # An embed token's user is the identity too.
    rid = api.client.post(f"{V1}/workspaces/{wid}/reports", json={"name": "r", "dataset_id": did, "is_published": True}).json()["id"]
    secret = api.client.post(f"{V1}/admin/service-tokens", json={"workspaceId": wid, "name": "erp"}).json()["token"]
    minted = api.client.post(f"{V1}/embed/token", headers={"Authorization": f"Bearer {secret}"}, json={
        "userEmail": "bo@example.com", "userName": "Bo", "reports": [rid], "datasets": [did], "rls": {"roles": ["Mine"]}})
    assert minted.status_code == 200, minted.text
    assert _total(api, wid, did, {"Authorization": f"Bearer {minted.json()['token']}"}).json()["rows"] == [[9]]


def test_userprincipalname_in_a_measure_says_where_it_belongs(api: ApiEnv) -> None:
    wid = api.workspace()
    did = api.client.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "d"}).json()["id"]
    api.client.post(f"{V1}/workspaces/{wid}/datasets/{did}/upload", files={"file": ("Sales.csv", SALES, "text/csv")}, data={"table_name": "Sales"})
    version = api.client.get(f"{V1}/workspaces/{wid}/datasets/{did}/definition").json()["model_version"]
    refused = api.client.post(
        f"{V1}/workspaces/{wid}/datasets/{did}/definition/measures",
        json={"model_version": version, "table": "Sales",
              "measure": {"name": "Me", "expression": 'CALCULATE(SUM(Sales[Amount]), Sales[Owner] = USERPRINCIPALNAME())'}},
    )
    assert refused.status_code == 422
    assert "USERPRINCIPALNAME() works only in row-level security rules" in refused.text
