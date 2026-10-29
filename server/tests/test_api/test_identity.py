from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"


def test_login_and_membership(api: ApiEnv) -> None:
    client = api.client
    created = client.post(
        f"{V1}/admin/users",
        json={
            "email": "Ada@Example.com",
            "name": "Ada",
            "password": "correct-horse",
            "platformAdmin": True,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["email"] == "ada@example.com"
    again = client.post(
        f"{V1}/admin/users",
        json={"email": "ada@example.com", "name": "Ada", "password": "correct-horse"},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "USER_EXISTS"

    bad = client.post(
        f"{V1}/auth/login", json={"email": "ada@example.com", "password": "nope"}
    )
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "LOGIN_FAILED"
    logged = client.post(
        f"{V1}/auth/login",
        json={"email": "ada@example.com", "password": "correct-horse"},
    )
    assert logged.status_code == 200, logged.text
    token = logged.json()["token"]

    viewer = client.post(
        f"{V1}/admin/users",
        json={
            "email": "view@example.com",
            "name": "View",
            "password": "viewer-password",
        },
    ).json()
    workspace = client.post(f"{V1}/workspaces", json={"name": "fleet"}).json()
    added = client.post(
        f"{V1}/workspaces/{workspace['id']}/members",
        json={"email": "view@example.com", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert added.status_code == 201, added.text
    view_token = client.post(
        f"{V1}/auth/login",
        json={"email": "view@example.com", "password": "viewer-password"},
    ).json()["token"]
    refused = client.post(
        f"{V1}/workspaces/{workspace['id']}/members",
        json={"email": "ada@example.com", "role": "editor"},
        headers={"Authorization": f"Bearer {view_token}"},
    )
    assert refused.status_code == 403
    removed = client.delete(
        f"{V1}/workspaces/{workspace['id']}/members/{viewer['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert removed.status_code == 204
