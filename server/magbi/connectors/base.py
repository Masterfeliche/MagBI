"""Connector ABC - every data-source connector implements this.

Connectors are synchronous: the drivers (pyodbc and friends) block. Async
callers use a thread pool. See docs/architecture/IMPORT-PIPELINE-SPEC.md 3.1.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType, TracebackType
from typing import Any, Literal, Self

from magbi.connectors.errors import ConnectorError, ErrorCode

# Conversions applied inside the source query:
#   "string"       - convert the column to text (types DuckDB cannot represent)
#   "utc_datetime" - normalise a timezone-aware timestamp to naive UTC
CastKind = Literal["string", "utc_datetime"]


@dataclass(frozen=True)
class SourceColumn:
    name: str
    data_type: str  # source-native type name, lower case (for example "nvarchar")
    is_nullable: bool = True
    is_primary_key: bool = False
    max_length: int | None = None  # characters/bytes; None or -1 means MAX
    precision: int | None = None
    scale: int | None = None


@dataclass(frozen=True)
class SourceTable:
    schema: str
    name: str
    columns: list[SourceColumn] = field(default_factory=list)
    estimated_rows: int | None = None
    kind: Literal["table", "view"] = "table"

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.name}"


@dataclass(frozen=True)
class ConnectionTestResult:
    success: bool
    server_version: str | None = None
    schemas: list[str] = field(default_factory=list)
    latency_ms: int | None = None
    error: str | None = None
    code: ErrorCode | None = None


class Connector(ABC):
    @abstractmethod
    def connect(self, config: Mapping[str, Any]) -> None:
        """Open the connection. Raises ``ConnectorError`` on failure."""

    @abstractmethod
    def close(self) -> None:
        """Release the connection. Safe to call more than once."""

    @abstractmethod
    def get_server_version(self) -> str: ...

    @abstractmethod
    def list_schemas(self) -> list[str]: ...

    @abstractmethod
    def list_tables(self, schema: str) -> list[SourceTable]:
        """Tables and views in ``schema`` with their columns."""

    @abstractmethod
    def execute_query(
        self, sql: str, *, batch_size: int = 10_000
    ) -> Iterator[tuple[Any, ...]]:
        """Run ``sql`` and stream the rows. Never loads the full result in memory."""

    def describe_query(self, sql: str) -> list[SourceColumn]:
        """The columns ``sql`` returns, without running it."""
        raise ConnectorError(
            ErrorCode.UNSUPPORTED, "this source cannot import from a SQL query"
        )

    @abstractmethod
    def get_row_count(self, schema: str, table: str) -> int: ...

    @abstractmethod
    def get_dialect(self) -> str:
        """The sqlglot dialect name for this source."""

    @abstractmethod
    def build_select(
        self,
        table: SourceTable,
        *,
        casts: Mapping[str, CastKind] = MappingProxyType({}),
        limit: int | None = None,
    ) -> str:
        """Build a SELECT of every column of ``table`` in the source dialect.

        Columns named in ``casts`` are converted in the source (see ``CastKind``).
        Identifiers are quoted; callers must pass a ``SourceTable`` obtained
        from ``list_tables`` and never raw user input.
        """

    # -- shared behaviour ----------------------------------------------------

    def find_table(self, schema: str, name: str) -> SourceTable:
        """Look up a table in the catalog or raise ``NOT_FOUND``."""
        for table in self.list_tables(schema):
            if table.name == name:
                return table
        raise ConnectorError(
            ErrorCode.NOT_FOUND, f"table {schema}.{name} does not exist"
        )

    def preview(
        self, schema: str, name: str, limit: int = 100
    ) -> Iterator[tuple[Any, ...]]:
        table = self.find_table(schema, name)
        return self.execute_query(
            self.build_select(table, limit=limit), batch_size=limit
        )

    def test_connection(self, config: Mapping[str, Any]) -> ConnectionTestResult:
        """Connect, read basic facts, disconnect. Never raises ``ConnectorError``."""
        started = time.perf_counter()
        try:
            self.connect(config)
            version = self.get_server_version()
            schemas = self.list_schemas()
        except ConnectorError as exc:
            return ConnectionTestResult(success=False, error=exc.message, code=exc.code)
        finally:
            self.close()
        latency = int((time.perf_counter() - started) * 1000)
        return ConnectionTestResult(
            success=True, server_version=version, schemas=schemas, latency_ms=latency
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
