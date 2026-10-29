"""Credential vault — AES-256-GCM encryption for connection secrets (FR-006).

Token format: ``v1:`` + urlsafe-base64(nonce[12] || ciphertext || tag[16]).
The key lives in server config (``MAGBI_CREDENTIAL_KEY``), never in the database.
The ``v1`` prefix leaves room for key rotation or a different cipher later.
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
NONCE_BYTES = 12
TOKEN_PREFIX = "v1:"


class CredentialError(Exception):
    """Raised when a secret cannot be encrypted or decrypted.

    Messages never contain plaintext, key material, or ciphertext.
    """


def generate_key() -> str:
    """Return a new random key encoded for ``MAGBI_CREDENTIAL_KEY``."""
    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode("ascii")


def parse_key(encoded: str) -> bytes:
    """Decode a base64 key and verify it is exactly 32 bytes."""
    try:
        raw = base64.urlsafe_b64decode(encoded.strip().encode("ascii"))
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise CredentialError("credential key is not valid base64") from exc
    if len(raw) != KEY_BYTES:
        raise CredentialError(
            f"credential key must decode to {KEY_BYTES} bytes, got {len(raw)}"
        )
    return raw


class CredentialVault:
    """Encrypts and decrypts short secrets such as database passwords."""

    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise CredentialError(f"credential key must be {KEY_BYTES} bytes")
        self._aead = AESGCM(key)

    @classmethod
    def from_encoded_key(cls, encoded: str) -> CredentialVault:
        return cls(parse_key(encoded))

    def __repr__(self) -> str:
        return "CredentialVault(key=<redacted>)"

    def encrypt(self, plaintext: str, *, aad: bytes | None = None) -> str:
        """Encrypt ``plaintext``. ``aad`` binds the secret to its context
        (for example a connection id) so it cannot be moved to another row."""
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, plaintext.encode("utf-8"), aad)
        return TOKEN_PREFIX + base64.urlsafe_b64encode(nonce + sealed).decode("ascii")

    def decrypt(self, token: str, *, aad: bytes | None = None) -> str:
        if not token.startswith(TOKEN_PREFIX):
            raise CredentialError("unsupported credential token version")
        try:
            blob = base64.urlsafe_b64decode(token[len(TOKEN_PREFIX) :].encode("ascii"))
        except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
            raise CredentialError("credential token is malformed") from exc
        if len(blob) <= NONCE_BYTES:
            raise CredentialError("credential token is truncated")
        nonce, sealed = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
        try:
            return self._aead.decrypt(nonce, sealed, aad).decode("utf-8")
        except InvalidTag as exc:
            raise CredentialError(
                "credential decryption failed (wrong key, context, or tampered data)"
            ) from exc
