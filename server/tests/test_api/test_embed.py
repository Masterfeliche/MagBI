import duckdb

from magbi.auth.tokens import EMBED_AUDIENCE, read_token
from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"


def test_a_service_token_mints_an_embed_token_for_its_workspace(api: ApiEnv) -> None:
    client = api.client
    workspace = client.post(f"{V1}/workspaces", json={"name": "host"}).json()
    other = client.post(f"{V1}/workspaces", json={"name": "other"}).json()
    dataset = client.post(
        f"{V1}/workspaces/{workspace['id']}/datasets", json={"name": "trips"}
    ).json()
    foreign = client.post(
        f"{V1}/workspaces/{other['id']}/datasets", json={"name": "trips"}
    ).json()
    secret = client.post(
        f"{V1}/admin/service-tokens",
        json={"workspaceId": workspace["id"], "name": "erp"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {secret}"}
    minted = client.post(
        f"{V1}/embed/token",
        headers=headers,
        json={
            "userEmail": "Ada@Example.com",
            "userName": "Ada",
            "datasets": [dataset["id"]],
            "rls": {"roles": ["DepartmentAccess"]},
        },
    )
    assert minted.status_code == 200, minted.text
    payload = read_token(
        minted.json()["token"],
        secret=api.settings.jwt_secret,
        audience=EMBED_AUDIENCE,
    )
    assert payload["type"] == "embed"
    assert payload["datasets"] == [dataset["id"]]
    assert payload["rls"]["roles"] == ["DepartmentAccess"]
    assert payload["email"] == "ada@example.com"

    user = client.post(
        f"{V1}/admin/users",
        json={"email": "ada@example.com", "name": "Ada", "password": "correct-horse"},
    )
    assert user.status_code == 201
    user_token = client.post(
        f"{V1}/auth/login",
        json={"email": "ada@example.com", "password": "correct-horse"},
    ).json()["token"]
    refused = client.post(
        f"{V1}/embed/token",
        headers={"Authorization": f"Bearer {user_token}"},
        json={
            "userEmail": "ada@example.com",
            "userName": "Ada",
            "datasets": [dataset["id"]],
        },
    )
    assert refused.status_code == 403

    outside = client.post(
        f"{V1}/embed/token",
        headers=headers,
        json={
            "userEmail": "ada@example.com",
            "userName": "Ada",
            "datasets": [foreign["id"]],
        },
    )
    assert outside.status_code == 422
    assert outside.json()["error"]["code"] == "OUTSIDE_WORKSPACE"


def test_an_embed_token_supplies_query_roles(api: ApiEnv) -> None:
    client = api.client
    workspace = client.post(f"{V1}/workspaces", json={"name": "host"}).json()
    dataset = client.post(
        f"{V1}/workspaces/{workspace['id']}/datasets", json={"name": "sales"}
    ).json()
    saved = client.put(
        f"{V1}/workspaces/{workspace['id']}/datasets/{dataset['id']}/definition",
        json={
            "model_version": 1,
            "definition": {
                "tables": [
                    {
                        "name": "Sales",
                        "columns": [
                            {"name": "Amount", "data_type": "integer"},
                            {"name": "Dept", "data_type": "string"},
                        ],
                        "measures": [
                            {
                                "name": "AllSales",
                                "expression": "CALCULATE(SUM(Sales[Amount]), ALL(Sales))",
                            }
                        ],
                    }
                ],
                "roles": [
                    {
                        "name": "DepartmentAccess",
                        "table_filters": [
                            {
                                "table": "Sales",
                                "expression": 'Sales[Dept] = "Finance"',
                            }
                        ],
                    }
                ],
            },
        },
    )
    assert saved.status_code == 200, saved.text
    path = api.services.store.live_path(dataset["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute('CREATE TABLE "Sales" ("Amount" INTEGER, "Dept" VARCHAR)')
    con.execute("INSERT INTO \"Sales\" VALUES (5, 'Finance'), (9, 'Other')")
    con.close()
    secret = client.post(
        f"{V1}/admin/service-tokens",
        json={"workspaceId": workspace["id"], "name": "erp"},
    ).json()["token"]
    embed = client.post(
        f"{V1}/embed/token",
        headers={"Authorization": f"Bearer {secret}"},
        json={
            "userEmail": "ada@example.com",
            "userName": "Ada",
            "datasets": [dataset["id"]],
            "rls": {"roles": ["DepartmentAccess"]},
        },
    ).json()["token"]
    queried = client.post(
        f"{V1}/workspaces/{workspace['id']}/datasets/{dataset['id']}/query",
        headers={"Authorization": f"Bearer {embed}"},
        json={
            "query": {
                "select": [{"measure": {"table": "Sales", "measure": "AllSales"}}]
            },
            "roles": ["Nope"],
        },
    )
    assert queried.status_code == 200, queried.text
    assert queried.json()["rows"] == [[5]]
    client.post(
        f"{V1}/admin/users",
        json={
            "email": "view@example.com",
            "name": "View",
            "password": "viewer-password",
        },
    )
    client.post(
        f"{V1}/workspaces/{workspace['id']}/members",
        json={"email": "view@example.com", "role": "viewer"},
    )
    viewer = client.post(
        f"{V1}/auth/login",
        json={"email": "view@example.com", "password": "viewer-password"},
    ).json()["token"]
    refused = client.post(
        f"{V1}/workspaces/{workspace['id']}/datasets/{dataset['id']}/query",
        headers={"Authorization": f"Bearer {viewer}"},
        json={
            "query": {
                "select": [{"measure": {"table": "Sales", "measure": "AllSales"}}]
            },
            "roles": ["DepartmentAccess"],
        },
    )
    assert refused.status_code == 403
