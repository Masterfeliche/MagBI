"""Reject anything but one read-only SELECT before it is sent to a source.

This is a guard in front of the source's own permissions, not a replacement
for a least-privilege login.
"""

from __future__ import annotations

import re

from magbi.connectors.errors import ConnectorError, ErrorCode

_WRITES = frozenset(
    {
        "INSERT", "UPDATE", "DELETE", "MERGE", "INTO", "EXEC", "EXECUTE", "DROP",
        "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE", "DENY", "BACKUP",
        "RESTORE", "DBCC", "SHUTDOWN", "KILL", "BULK", "OPENROWSET", "OPENQUERY",
        "OPENDATASOURCE", "SP_EXECUTESQL", "XP_CMDSHELL", "USE", "DECLARE", "SET",
    }
)
_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_STRINGS = re.compile(r"N?'(?:[^']|'')*'")
_BRACKETS = re.compile(r"\[(?:[^\]]|\]\])*\]|\"(?:[^\"]|\"\")*\"")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def check_read_only(sql: str) -> str:
    """Return ``sql`` stripped of a trailing semicolon, or raise if it may write."""
    code = _STRINGS.sub("''", _COMMENTS.sub(" ", sql))
    code = _BRACKETS.sub("x", code).strip().rstrip(";").strip()
    if not code:
        raise ConnectorError(ErrorCode.INVALID_CONFIG, "the query is empty")
    if ";" in code:
        raise ConnectorError(ErrorCode.INVALID_CONFIG, "the query must be one statement")
    words = [word.upper() for word in _WORD.findall(code)]
    if not words or words[0] not in {"SELECT", "WITH"}:
        raise ConnectorError(
            ErrorCode.INVALID_CONFIG, "the query must start with SELECT or WITH"
        )
    found = sorted(set(words) & _WRITES)
    if found:
        raise ConnectorError(
            ErrorCode.INVALID_CONFIG,
            f"the query must only read data; it uses {', '.join(found)}",
        )
    return sql.strip().rstrip(";").strip()
