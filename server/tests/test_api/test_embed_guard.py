"""An embed token can read its own reports and query its own datasets, nothing else."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"


@dataclass
class EmbedSetup:
    wid: str
    other_wid: str
    did: str
    other_did: str
    report: str
    other_report: str
    foreign_report: str
    headers: dict[str, str]


def _report(api: ApiEnv, wid: str, did: str, name: str) -> str:
    r = api.client.post(
        f"{V1}/workspaces/{wid}/reports",
        json={"name": name, "dataset_id": did, "is_published": True},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


@pytest.fixture
def embed(api: ApiEnv) -> EmbedSetup:
    client = api.client
    wid = api.workspace("host")
    other_wid = api.workspace("other")
    did = client.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "gl"}).json()["id"]
    other_did = client.post(
        f"{V1}/workspaces/{wid}/datasets", json={"name": "hr"}
    ).json()["id"]
    foreign_did = client.post(
        f"{V1}/workspaces/{other_wid}/datasets", json={"name": "gl"}
    ).json()["id"]
    report = _report(api, wid, did, "Ledger")
    other_report = _report(api, wid, did, "Spend")
    foreign_report = _report(api, other_wid, foreign_did, "Ledger")
    secret = client.post(
        f"{V1}/admin/service-tokens", json={"workspaceId": wid, "name": "erp"}
    ).json()["token"]
    minted = client.post(
        f"{V1}/embed/token",
        headers={"Authorization": f"Bearer {secret}"},
        json={
            "userEmail": "ada@example.com",
            "userName": "Ada",
            "reports": [report],
            "datasets": [did],
        },
    )
    assert minted.status_code == 200, minted.text
    token = minted.json()["token"]
    return EmbedSetup(
        wid, other_wid, did, other_did, report, other_report, foreign_report,
        {"Authorization": f"Bearer {token}"},
    )


def test_an_embed_token_reads_its_own_published_report(
    api: ApiEnv, embed: EmbedSetup
) -> None:
    r = api.client.get(
        f"{V1}/workspaces/{embed.wid}/reports/{embed.report}", headers=embed.headers
    )
    assert r.status_code == 200, r.text
    assert api.client.get(f"{V1}/auth/whoami", headers=embed.headers).status_code == 200


@pytest.mark.parametrize("method", ["PUT", "DELETE", "POST", "PATCH"])
def test_an_embed_token_cannot_change_a_report(
    api: ApiEnv, embed: EmbedSetup, method: str
) -> None:
    url = f"{V1}/workspaces/{embed.wid}/reports/{embed.report}"
    r = api.client.request(
        method, url, headers=embed.headers, json={"name": "hijacked", "is_published": False}
    )
    # PUT exists on this route and must be refused by the guard; the others have no
    # route, so the router answers 405 before the guard runs.
    expected = {403} if method == "PUT" else {403, 405}
    assert r.status_code in expected, r.text
    after = api.client.get(url).json()
    assert after["name"] == "Ledger"
    assert after["is_published"] is True


def test_an_embed_token_cannot_create_or_list_reports(
    api: ApiEnv, embed: EmbedSetup
) -> None:
    url = f"{V1}/workspaces/{embed.wid}/reports"
    assert api.client.get(url, headers=embed.headers).status_code == 403
    created = api.client.post(
        url, headers=embed.headers, json={"name": "x", "dataset_id": embed.did}
    )
    assert created.status_code == 403


def test_an_embed_token_cannot_read_a_report_outside_its_scope(
    api: ApiEnv, embed: EmbedSetup
) -> None:
    same_workspace = f"{V1}/workspaces/{embed.wid}/reports/{embed.other_report}"
    foreign = f"{V1}/workspaces/{embed.other_wid}/reports/{embed.foreign_report}"
    moved = f"{V1}/workspaces/{embed.other_wid}/reports/{embed.report}"
    for url in (same_workspace, foreign, moved):
        assert api.client.get(url, headers=embed.headers).status_code == 403, url


def test_an_embed_token_queries_only_its_own_datasets(
    api: ApiEnv, embed: EmbedSetup
) -> None:
    body = {"query": {"from": [], "select": []}}
    other = f"{V1}/workspaces/{embed.wid}/datasets/{embed.other_did}/query"
    assert api.client.post(other, headers=embed.headers, json=body).status_code == 403
    foreign = f"{V1}/workspaces/{embed.other_wid}/datasets/{embed.did}/query"
    assert api.client.post(foreign, headers=embed.headers, json=body).status_code == 403


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/workspaces/{wid}/datasets"),
        ("GET", "/workspaces/{wid}/datasets/{did}/definition"),
        ("PUT", "/workspaces/{wid}/datasets/{did}"),
        ("POST", "/workspaces/{wid}/datasets/{did}/refresh"),
        ("POST", "/workspaces/{wid}/datasets/{did}/upload"),
        ("GET", "/workspaces/{wid}/members"),
        ("GET", "/workspaces/{wid}/connections"),
        ("POST", "/embed/token"),
    ],
)
def test_an_embed_token_is_kept_off_management_routes(
    api: ApiEnv, embed: EmbedSetup, method: str, path: str
) -> None:
    url = V1 + path.format(wid=embed.wid, did=embed.did)
    r = api.client.request(method, url, headers=embed.headers)
    assert r.status_code == 403, f"{method} {url}: {r.status_code}"
