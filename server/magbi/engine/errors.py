"""Errors a caller can fix by changing the semantic query or the model."""

from __future__ import annotations


class QueryError(Exception):
    """A query the engine will not run. ``code`` is stable."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)
