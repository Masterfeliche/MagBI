"""Typed connector errors that the API can translate to user-facing messages."""

from __future__ import annotations

import enum


class ErrorCode(enum.StrEnum):
    AUTH_FAILED = "AUTH_FAILED"
    UNREACHABLE = "UNREACHABLE"
    TIMEOUT = "TIMEOUT"
    NOT_FOUND = "NOT_FOUND"
    INVALID_CONFIG = "INVALID_CONFIG"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_CONNECTED = "NOT_CONNECTED"
    QUERY_FAILED = "QUERY_FAILED"


class ConnectorError(Exception):
    """A connector failure with a stable machine-readable code.

    ``message`` is safe to show to users: connectors must scrub passwords and
    connection strings before raising.
    """

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"
