"""Bind @name parameters in a read-only SELECT. Null means All."""

from __future__ import annotations

import re
from collections.abc import Mapping

_PARAM = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ParameterError(ValueError):
    """A parameter name or value cannot be bound safely."""


def bind_sql_parameters(sql: str, values: Mapping[str, str | None]) -> str:
    """Replace each @name. A missing or None value becomes NULL."""
    known = {key.casefold(): key for key in values}

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        key = known.get(name.casefold())
        if key is None:
            raise ParameterError(f"unknown parameter @{name}")
        return _literal(values[key])

    return _PARAM.sub(replace, sql)


def _literal(value: str | None) -> str:
    if value is None or value == "":
        return "NULL"
    if len(value) > 128 or any(ord(ch) < 32 for ch in value):
        raise ParameterError("parameter value is not allowed")
    return "N'" + value.replace("'", "''") + "'"


def parameter_names(sql: str) -> tuple[str, ...]:
    found: list[str] = []
    for name in _PARAM.findall(sql):
        if name not in found and _NAME.match(name):
            found.append(name)
    return tuple(found)
