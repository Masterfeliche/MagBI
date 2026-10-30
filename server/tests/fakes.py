"""In-memory connector used by unit tests (no database needed)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import MappingProxyType
from typing import Any

from magbi.connectors.base import CastKind, Connector, SourceColumn, SourceTable
from magbi.connectors.errors import ConnectorError, ErrorCode


class FakeConnector(Connector):
    def __init__(
        self,
        tables: list[SourceTable] | None = None,
        rows: dict[str, list[tuple[Any, ...]]] | None = None,
        *,
        fail_connect: ConnectorError | None = None,
        fail_after_rows: int | None = None,
        query_results: dict[str, tuple[list[SourceColumn], list[tuple[Any, ...]]]]
        | None = None,
    ) -> None:
        self.tables = tables or []
        self.query_results = query_results or {}
        self.rows = rows or {}
        self.fail_connect = fail_connect
        self.fail_after_rows = fail_after_rows
        self.connected = False
        self.close_calls = 0
        self.queries: list[str] = []
        self.config: Mapping[str, Any] | None = None

    def connect(self, config: Mapping[str, Any]) -> None:
        if self.fail_connect is not None:
            raise self.fail_connect
        self.config = config
        self.connected = True

    def close(self) -> None:
        self.close_calls += 1
        self.connected = False

    def _require(self) -> None:
        if not self.connected:
            raise ConnectorError(ErrorCode.NOT_CONNECTED, "not connected")

    def get_server_version(self) -> str:
        self._require()
        return "FakeDB 1.0"

    def list_schemas(self) -> list[str]:
        self._require()
        return sorted({t.schema for t in self.tables})

    def list_tables(self, schema: str) -> list[SourceTable]:
        self._require()
        return [t for t in self.tables if t.schema == schema]

    def execute_query(
        self, sql: str, *, batch_size: int = 10_000
    ) -> Iterator[tuple[Any, ...]]:
        self._require()
        self.queries.append(sql)
        if sql in self.query_results:
            yield from self.query_results[sql][1]
            return
        key = sql.split("|", 1)[0]  # fake SQL format: "<schema.table>|limit"
        data = self.rows.get(key, [])
        limit = (
            int(sql.split("|", 1)[1]) if "|" in sql and sql.split("|", 1)[1] else None
        )
        if limit is not None:
            data = data[:limit]
        for i, row in enumerate(data):
            if self.fail_after_rows is not None and i >= self.fail_after_rows:
                raise ConnectorError(ErrorCode.UNREACHABLE, "connection lost")
            yield row

    def describe_query(self, sql: str) -> list[SourceColumn]:
        self._require()
        if sql not in self.query_results:
            raise ConnectorError(ErrorCode.QUERY_FAILED, "unknown query")
        return self.query_results[sql][0]

    def get_row_count(self, schema: str, table: str) -> int:
        self._require()
        return len(self.rows.get(f"{schema}.{table}", []))

    def get_dialect(self) -> str:
        return "tsql"

    def build_select(
        self,
        table: SourceTable,
        *,
        casts: Mapping[str, CastKind] = MappingProxyType({}),
        limit: int | None = None,
    ) -> str:
        return f"{table.qualified_name}|{limit if limit is not None else ''}"
