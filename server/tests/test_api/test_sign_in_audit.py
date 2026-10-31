"""Every sign-in, and every failed attempt, is written to the audit log."""

from __future__ import annotations

import json

import sqlalchemy as sa

from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"


def _audit(api: ApiEnv) -> list[tuple[str, str, str | None, dict]]:
    engine = sa.create_engine(api.settings.database_url.replace("+aiosqlite", ""))
    with engine.connect() as con:
        rows = con.execute(sa.text("SELECT principal, action, object_id, detail FROM audit_log ORDER BY id")).all()
    engine.dispose()
    return [(row[0], row[1], row[2], json.loads(row[3]) if isinstance(row[3], str) else row[3]) for row in rows]


def test_sign_ins_and_failed_attempts_are_recorded_without_the_password(api: ApiEnv) -> None:
    created = api.client.post(
        f"{V1}/admin/users", json={"email": "ada@example.com", "name": "Ada", "password": "correct-horse"}
    ).json()
    api.client.post(f"{V1}/auth/login", json={"email": "ada@example.com", "password": "wrong-horse"})
    api.client.post(f"{V1}/auth/login", json={"email": "nobody@example.com", "password": "anything-1"})
    ok = api.client.post(f"{V1}/auth/login", json={"email": "Ada@Example.com", "password": "correct-horse"})
    assert ok.status_code == 200

    rows = _audit(api)
    assert [(principal, action) for principal, action, _id, _detail in rows] == [
        ("ada@example.com", "sign_in_failed"),
        ("nobody@example.com", "sign_in_failed"),
        ("ada@example.com", "sign_in"),
    ]
    assert rows[0][3]["reason"] == "wrong_password" and rows[0][2] == created["id"]
    assert rows[1][3]["reason"] == "unknown_email" and rows[1][2] is None
    assert rows[2][2] == created["id"]
    assert "horse" not in json.dumps(rows)


def test_a_failed_attempt_still_answers_only_wrong(api: ApiEnv) -> None:
    api.client.post(f"{V1}/admin/users", json={"email": "ada@example.com", "name": "Ada", "password": "correct-horse"})
    for body in ({"email": "ada@example.com", "password": "nope-nope"}, {"email": "ghost@example.com", "password": "nope-nope"}):
        r = api.client.post(f"{V1}/auth/login", json=body)
        assert r.status_code == 401
        assert r.json()["error"] == {"code": "LOGIN_FAILED", "message": "email or password is wrong"}
