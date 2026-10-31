"""Data alerts, notifications, email subscriptions and PDF export."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest

from magbi.metadata.models import utcnow
from magbi.notify import alerts, subscriptions
from magbi.notify.mail import MemoryMailer
from magbi.notify.pdf import ExportError
from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"
SALES = b"Owner,Amount\nada@example.com,5\nada@example.com,1\nbo@example.com,9\n"
MORE = b"Owner,Amount\nada@example.com,5\nada@example.com,1\nbo@example.com,9\nbo@example.com,30\n"


def _user(api: ApiEnv, email: str) -> dict[str, str]:
    api.client.post(f"{V1}/admin/users", json={"email": email, "name": email, "password": "pass-word-1"})
    token = api.client.post(f"{V1}/auth/login", json={"email": email, "password": "pass-word-1"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _member(api: ApiEnv, wid: str, email: str = "ed@example.com", role: str = "editor") -> dict[str, str]:
    _user(api, email)
    api.client.post(f"{V1}/workspaces/{wid}/members", json={"email": email, "role": role})
    # Sign in again so the token carries the new role.
    token = api.client.post(f"{V1}/auth/login", json={"email": email, "password": "pass-word-1"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _card_report(api: ApiEnv) -> tuple[str, str, str]:
    wid = api.workspace()
    did = api.client.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "d"}).json()["id"]
    api.client.post(f"{V1}/workspaces/{wid}/datasets/{did}/upload", files={"file": ("Sales.csv", SALES, "text/csv")}, data={"table_name": "Sales"})
    current = api.client.get(f"{V1}/workspaces/{wid}/datasets/{did}/definition").json()
    model = current["definition"]
    next(t for t in model["tables"] if t["name"] == "Sales")["measures"].append({"name": "Total", "expression": "SUM(Sales[Amount])"})
    api.client.put(f"{V1}/workspaces/{wid}/datasets/{did}/definition", json={"model_version": current["model_version"], "definition": model})
    total = {"table": "Sales", "measure": "Total"}
    definition = {
        "schemaVersion": "1.0", "name": "Sales", "datasetId": did,
        "pages": [{"name": "p", "displayName": "Page 1", "width": 1760, "height": 990, "visuals": [
            {"id": "card", "type": "card", "x": 0, "y": 0, "width": 300, "height": 150, "wells": {"y-axis": [total]}, "properties": {"title": "Sales total"}},
            {"id": "bo-card", "type": "card", "x": 0, "y": 200, "width": 300, "height": 150, "wells": {"y-axis": [total]},
             "filters": [{"table": "Sales", "column": "Owner", "type": "basic", "config": {"operator": "eq", "values": ["bo@example.com"]}}]},
            {"id": "chart", "type": "clusteredColumn", "x": 400, "y": 0, "width": 300, "height": 150, "wells": {"y-axis": [total]}},
        ]}],
    }
    made = api.client.post(f"{V1}/workspaces/{wid}/reports", json={"name": "Sales", "dataset_id": did, "definition": definition, "is_published": True})
    assert made.status_code == 201, made.text
    return wid, did, made.json()["id"]


def _reload(api: ApiEnv, wid: str, did: str, data: bytes) -> None:
    up = api.client.post(f"{V1}/workspaces/{wid}/datasets/{did}/upload", files={"file": ("Sales.csv", data, "text/csv")}, data={"table_name": "Sales"})
    assert up.status_code == 200, up.text


def _check(api: ApiEnv, did: str) -> int:
    return int(api.client.portal.call(alerts.check_alerts, api.services, uuid.UUID(did)))  # type: ignore[union-attr]


def test_an_alert_fires_once_when_its_card_crosses_the_threshold(api: ApiEnv) -> None:
    wid, did, rid = _card_report(api)
    mailer = MemoryMailer()
    api.services.mailer = mailer
    ada = _user(api, "ada@example.com")
    api.client.post(f"{V1}/workspaces/{wid}/reports/{rid}/shares", json={"email": "ada@example.com"})

    made = api.client.post(f"{V1}/me/alerts", headers=ada, json={"reportId": rid, "visualId": "card", "condition": "gt", "threshold": 20})
    assert made.status_code == 201, made.text
    assert made.json()["lastValue"] == 15 and made.json()["visualTitle"] == "Sales total"
    assert _check(api, did) == 0

    _reload(api, wid, did, MORE)
    assert _check(api, did) == 1
    assert _check(api, did) == 0  # still above: no second notification
    inbox = api.client.get(f"{V1}/me/notifications", headers=ada).json()
    assert inbox["unread"] == 1
    assert inbox["items"][0]["title"] == "Sales total is above 20"
    assert "is 45" in inbox["items"][0]["body"] and inbox["items"][0]["link"].endswith(f"/reports/{rid}/view")
    assert [m["subject"] for m in mailer.sent] == ["MagBI alert: Sales total is above 20"]

    assert api.client.post(f"{V1}/me/notifications/read", headers=ada, json={}).status_code == 204
    assert api.client.get(f"{V1}/me/notifications", headers=ada).json()["unread"] == 0

    # Falls back under, then crosses again: fires again.
    _reload(api, wid, did, SALES)
    assert _check(api, did) == 0
    _reload(api, wid, did, MORE)
    assert _check(api, did) == 1


def test_an_alert_reads_the_visuals_own_filters(api: ApiEnv) -> None:
    wid, _, rid = _card_report(api)
    ed = _member(api, wid)
    made = api.client.post(f"{V1}/me/alerts", headers=ed, json={"reportId": rid, "visualId": "bo-card", "condition": "lte", "threshold": 9})
    assert made.status_code == 201, made.text
    assert made.json()["lastValue"] == 9


def test_alerts_watch_single_value_visuals_only(api: ApiEnv) -> None:
    wid, _, rid = _card_report(api)
    ed = _member(api, wid, role="viewer")
    refused = api.client.post(f"{V1}/me/alerts", headers=ed, json={"reportId": rid, "visualId": "chart", "condition": "gt", "threshold": 1})
    assert refused.status_code == 422 and "cards" in refused.json()["error"]["message"]
    missing = api.client.post(f"{V1}/me/alerts", headers=ed, json={"reportId": rid, "visualId": "nope", "condition": "gt", "threshold": 1})
    assert missing.status_code == 422


def test_an_alert_stops_when_its_owner_loses_access(api: ApiEnv) -> None:
    wid, did, rid = _card_report(api)
    bo = _user(api, "bo@example.com")
    share = api.client.post(f"{V1}/workspaces/{wid}/reports/{rid}/shares", json={"email": "bo@example.com"}).json()
    assert api.client.post(f"{V1}/me/alerts", headers=bo, json={"reportId": rid, "visualId": "card", "condition": "gt", "threshold": 1}).status_code == 201
    api.client.delete(f"{V1}/workspaces/{wid}/reports/{rid}/shares/{share['userId']}")
    assert _check(api, did) == 0
    outsider = _user(api, "cy@example.com")
    assert api.client.post(f"{V1}/me/alerts", headers=outsider, json={"reportId": rid, "visualId": "card", "condition": "gt", "threshold": 1}).status_code == 404


def test_subscriptions_need_mail_and_send_on_schedule(api: ApiEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    wid, _, rid = _card_report(api)
    ed = _member(api, wid, role="viewer")
    body = {"reportId": rid, "cron": "0 7 * * 1"}
    refused = api.client.post(f"{V1}/me/subscriptions", headers=ed, json=body)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "MAIL_NOT_CONFIGURED"

    mailer = MemoryMailer()
    api.services.mailer = mailer
    printed: list[Any] = []

    async def fake_export(svc: Any, report: Any, actor: Any) -> bytes:
        printed.append((report.name, actor.email))
        return b"%PDF-1.7 fake"

    monkeypatch.setattr(subscriptions, "export_report", fake_export)
    assert api.client.post(f"{V1}/me/subscriptions", headers=ed, json={**body, "cron": "every day"}).status_code == 422
    made = api.client.post(f"{V1}/me/subscriptions", headers=ed, json=body)
    assert made.status_code == 201, made.text
    assert api.client.get(f"{V1}/me/subscriptions", headers=ed).json()["mailReady"] is True

    now = utcnow()
    assert api.client.portal.call(subscriptions.send_due_subscriptions, api.services, now) == 0  # type: ignore[union-attr]
    later = now + timedelta(days=8)
    assert api.client.portal.call(subscriptions.send_due_subscriptions, api.services, later) == 1  # type: ignore[union-attr]
    assert api.client.portal.call(subscriptions.send_due_subscriptions, api.services, later) == 0  # type: ignore[union-attr]
    sent = mailer.sent[0]
    assert sent["subject"] == "Sales: your MagBI subscription"
    attachment = sent["attachments"][0]  # type: ignore[index]
    assert attachment.filename.startswith("Sales ") and attachment.content.startswith(b"%PDF")
    assert printed and printed[0][0] == "Sales"

    sid = made.json()["id"]
    assert api.client.post(f"{V1}/me/subscriptions/{sid}/send", headers=ed).status_code == 200
    assert len(mailer.sent) == 2
    assert api.client.delete(f"{V1}/me/subscriptions/{sid}", headers=ed).status_code == 204
    assert api.client.get(f"{V1}/me/subscriptions", headers=ed).json()["items"] == []
    assert wid


def test_pdf_export_follows_report_access(api: ApiEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    import magbi.api.notify as notify_api

    wid, _, rid = _card_report(api)
    calls: list[str] = []

    async def fake_export(svc: Any, report: Any, actor: Any) -> bytes:
        calls.append(actor.email)
        return b"%PDF-1.7 fake"

    monkeypatch.setattr(notify_api, "export_report", fake_export)
    ada = _user(api, "ada@example.com")
    url = f"{V1}/workspaces/{wid}/reports/{rid}/export.pdf"
    assert api.client.get(url, headers=ada).status_code == 403
    api.client.post(f"{V1}/workspaces/{wid}/reports/{rid}/shares", json={"email": "ada@example.com"})
    got = api.client.get(url, headers=ada)
    assert got.status_code == 200 and got.headers["content-type"] == "application/pdf"
    assert 'filename="Sales ' in got.headers["content-disposition"]
    assert calls == ["ada@example.com"]

    async def broken(svc: Any, report: Any, actor: Any) -> bytes:
        raise ExportError("PDF export needs Chrome or Edge on the server; set MAGBI_CHROME_PATH")

    monkeypatch.setattr(notify_api, "export_report", broken)
    failed = api.client.get(url, headers=ada)
    assert failed.status_code == 503 and "MAGBI_CHROME_PATH" in failed.json()["error"]["message"]


def test_a_scheduler_pass_with_nothing_due_does_nothing(api: ApiEnv) -> None:
    _card_report(api)
    api.services.mailer = MemoryMailer()
    api.client.portal.call(subscriptions.tick, api.services)  # type: ignore[union-attr]
    assert api.services.mailer.sent == []  # type: ignore[attr-defined]
