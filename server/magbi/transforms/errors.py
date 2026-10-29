"""Errors a caller can fix by changing a transform step."""

from __future__ import annotations


class TransformError(Exception):
    """A step list the engine will not run. ``code`` is stable."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)
