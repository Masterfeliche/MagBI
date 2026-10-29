from datetime import UTC, datetime, timedelta

from magbi.auth.tokens import (
    USER_AUDIENCE,
    TokenError,
    hash_password,
    issue_token,
    read_token,
    user_claims,
    verify_password,
)

SECRET = "test-secret-test-secret-test-secret"


def test_a_password_and_a_user_token_round_trip() -> None:
    stored = hash_password("correct-horse")
    assert verify_password("correct-horse", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("correct-horse", None)
    claims = user_claims(
        "user-1",
        "ada@example.com",
        "Ada",
        [{"id": "ws-1", "role": "editor"}],
        ttl_minutes=60,
    )
    token = issue_token(claims, secret=SECRET)
    payload = read_token(token, secret=SECRET, audience=USER_AUDIENCE)
    assert payload["sub"] == "user-1"
    assert payload["workspaces"] == [{"id": "ws-1", "role": "editor"}]


def test_a_wrong_audience_and_an_expired_token_fail() -> None:
    claims = user_claims("user-1", "ada@example.com", "Ada", [], ttl_minutes=60)
    token = issue_token(claims, secret=SECRET)
    try:
        read_token(token, secret=SECRET, audience="other")
    except TokenError as exc:
        assert exc.code == "TOKEN_INVALID"
    else:
        raise AssertionError("expected TOKEN_INVALID")
    expired = dict(claims)
    expired["exp"] = int((datetime.now(UTC) - timedelta(minutes=5)).timestamp())
    old = issue_token(expired, secret=SECRET)
    try:
        read_token(old, secret=SECRET, audience=USER_AUDIENCE)
    except TokenError as exc:
        assert exc.code == "TOKEN_EXPIRED"
    else:
        raise AssertionError("expected TOKEN_EXPIRED")
