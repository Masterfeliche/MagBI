"""Query result cache keyed by dataset id, version, and the canonical query.

A new ``current_version`` misses. Redis errors are ignored so a query still runs.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from magbi.engine.executor import run_query
from magbi.engine.semantic import SemanticQuery
from magbi.model.schema import DatasetDefinition

TTL_SECONDS = 300


class QueryCache(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...

    def set(self, key: str, value: dict[str, Any], ttl: int = TTL_SECONDS) -> None: ...


class MemoryQueryCache:
    """Process-local stand-in used by tests and when Redis is not wanted."""

    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        found = self.values.get(key)
        return None if found is None else dict(found)

    def set(self, key: str, value: dict[str, Any], ttl: int = TTL_SECONDS) -> None:
        del ttl
        self.values[key] = dict(value)


class RedisQueryCache:
    def __init__(self, client: Any) -> None:
        self._client = client

    def get(self, key: str) -> dict[str, Any] | None:
        raw = self._client.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            return None
        return loaded

    def set(self, key: str, value: dict[str, Any], ttl: int = TTL_SECONDS) -> None:
        self._client.set(key, json.dumps(value), ex=ttl)


def cache_key(dataset_id: str, version: int, query: SemanticQuery) -> str:
    payload = json.dumps(
        query.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(f"{dataset_id}|{version}|{payload}".encode()).hexdigest()
    return f"magbi:query:{digest}"


def run_cached(
    model: DatasetDefinition,
    query: SemanticQuery,
    con: Any,
    *,
    cache: QueryCache | None,
    dataset_id: str,
    version: int,
) -> dict[str, Any]:
    """Return a cached result when one exists. Cache failures still run the query."""
    key = cache_key(dataset_id, version, query)
    if cache is not None:
        try:
            hit = cache.get(key)
        except (OSError, RuntimeError, ValueError, TypeError):
            hit = None
        if hit is not None:
            return hit
    result = run_query(model, query, con)
    if cache is not None:
        try:
            cache.set(key, result)
        except (OSError, RuntimeError, ValueError, TypeError):
            return result
    return result
