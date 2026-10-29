"""Connector ABC — all data-source connectors implement this."""

from abc import ABC, abstractmethod
from typing import Any


class Connector(ABC):
    @abstractmethod
    async def test_connection(self) -> bool: ...

    @abstractmethod
    async def get_tables(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_schema(self, table: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def read_table(self, table: str, *, limit: int | None = None) -> Any: ...
