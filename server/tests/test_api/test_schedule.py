from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"


def test_a_schedule_is_stored_and_a_bad_cron_is_rejected(api: ApiEnv) -> None:
    client = api.client
    wid = api.workspace()
    created = client.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "d"}).json()
    did = created["id"]
    url = f"{V1}/workspaces/{wid}/datasets/{did}/schedule"
    bad = client.put(url, json={"cron": "every half hour"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "BAD_SCHEDULE"
    saved = client.put(url, json={"cron": "*/30 * * * *"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["cron"] == "*/30 * * * *"
    body = client.get(f"{V1}/workspaces/{wid}/datasets/{did}").json()
    assert body["schedule_cron"] == "*/30 * * * *"
    cleared = client.delete(url)
    assert cleared.status_code == 204
    assert (
        client.get(f"{V1}/workspaces/{wid}/datasets/{did}").json()["schedule_cron"]
        is None
    )
