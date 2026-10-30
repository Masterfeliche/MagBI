"""Password hashes and signed tokens.

HS256 uses the shared secret. RS256 is used only when a private key is
configured, and a token signed with the other algorithm is rejected.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

ISSUER = "magbi"
USER_AUDIENCE = "magbi-api"
EMBED_AUDIENCE = "magbi-embed"
_ITERATIONS = 200_000


class TokenError(Exception):
    """A token or password the caller can replace."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    parts = stored.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    try:
        iterations = int(parts[1])
        salt = base64.urlsafe_b64decode(parts[2].encode())
        expected = base64.urlsafe_b64decode(parts[3].encode())
    except (ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return hmac.compare_digest(digest, expected)


def issue_token(
    claims: dict[str, Any],
    *,
    secret: str,
    algorithm: str = "HS256",
    private_key: str | None = None,
) -> str:
    """Sign ``claims``. RS256 uses ``private_key`` and ignores ``secret``."""
    key = _signing_key(algorithm, secret, private_key)
    return str(jwt.encode(claims, key, algorithm=algorithm))


def read_token(
    token: str,
    *,
    secret: str,
    algorithm: str = "HS256",
    public_key: str | None = None,
    audience: str,
) -> dict[str, Any]:
    """Check the signature, issuer, audience, and expiry."""
    key = public_key if algorithm == "RS256" else secret
    if algorithm == "RS256" and not public_key:
        raise TokenError("TOKEN_INVALID", "RS256 requires a public key")
    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=[algorithm],
            audience=audience,
            issuer=ISSUER,
        )
    except JWTError as exc:
        code = "TOKEN_EXPIRED" if "expired" in str(exc).lower() else "TOKEN_INVALID"
        raise TokenError(code, "token is not valid") from None
    if not isinstance(payload, dict):
        raise TokenError("TOKEN_INVALID", "token is not valid")
    return payload


def user_claims(
    user_id: str,
    email: str,
    name: str,
    workspaces: list[dict[str, str]],
    *,
    ttl_minutes: int,
    platform_admin: bool = False,
) -> dict[str, Any]:
    return _timed(
        {
            "sub": user_id,
            "email": email,
            "name": name,
            "type": "user",
            "workspaces": workspaces,
            "platformAdmin": platform_admin,
            "aud": USER_AUDIENCE,
        },
        ttl_minutes,
    )


def embed_claims(
    *,
    email: str,
    name: str,
    workspace_id: str,
    reports: list[str],
    datasets: list[str],
    roles: list[str],
    ttl_minutes: int,
) -> dict[str, Any]:
    return _timed(
        {
            "sub": email,
            "email": email,
            "name": name,
            "type": "embed",
            "workspaceId": workspace_id,
            "reports": reports,
            "datasets": datasets,
            "rls": {"roles": roles},
            "aud": EMBED_AUDIENCE,
        },
        ttl_minutes,
    )


def _timed(claims: dict[str, Any], ttl_minutes: int) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        **claims,
        "iss": ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
    }


def _signing_key(algorithm: str, secret: str, private_key: str | None) -> str:
    if algorithm == "RS256":
        if not private_key:
            raise TokenError("TOKEN_INVALID", "RS256 requires a private key")
        return private_key
    if algorithm != "HS256":
        raise TokenError("TOKEN_INVALID", f"algorithm {algorithm} is not supported")
    return secret
