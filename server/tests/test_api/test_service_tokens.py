from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"


def test_a_service_token_works_until_it_is_revoked(api: ApiEnv) -> None:
    client = api.client
    workspace = client.post(f"{V1}/workspaces", json={"name": "host"}).json()
    created = client.post(
        f"{V1}/admin/service-tokens",
        json={"workspaceId": workspace["id"], "name": "erp"},
    )
    assert created.status_code == 201, created.text
    secret = created.json()["token"]
    assert secret.startswith("v2_svc_")
    listed = client.get(f"{V1}/admin/service-tokens").json()
    assert "token" not in listed[0]
    who = client.get(f"{V1}/auth/whoami", headers={"Authorization": f"Bearer {secret}"})
    assert who.status_code == 200, who.text
    assert who.json()["kind"] == "service"
    assert who.json()["workspaceId"] == workspace["id"]
    revoked = client.delete(f"{V1}/admin/service-tokens/{created.json()['id']}")
    assert revoked.status_code == 204
    again = client.get(f"{V1}/auth/whoami", headers={"Authorization": f"Bearer {secret}"})
    assert again.status_code == 401
    assert again.json()["error"]["code"] == "TOKEN_INVALID"
