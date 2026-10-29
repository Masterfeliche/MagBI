"""Errors raised while tokenising, parsing, binding, or compiling a formula."""

from __future__ import annotations


class DaxError(Exception):
    """A formula problem the user can fix. Line and column are 1-based."""

    def __init__(self, message: str, line: int, col: int) -> None:
        self.message = message
        self.line = line
        self.col = col
        super().__init__(f"{message} (line {line}, column {col})")
