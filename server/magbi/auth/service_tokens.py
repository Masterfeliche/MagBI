"""Opaque service tokens. Only the SHA-256 hash is stored."""

from __future__ import annotations

import hashlib
import secrets


def new_service_secret() -> tuple[str, str]:
    """Return ``(plaintext, hash)``. The plaintext is shown once."""
    raw = "v2_svc_" + secrets.token_urlsafe(32)
    return raw, hash_service_secret(raw)


def hash_service_secret(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
