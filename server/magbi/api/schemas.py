"""Request/response models and JSON helpers for the v1 API."""

from __future__ import annotations

import datetime as dt
import math
import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

Name = Field(min_length=1, max_length=200)
MAX_PREVIEW_ROWS = 1000
DEFAULT_PREVIEW_ROWS = 100
MAX_BINARY_PREVIEW_BYTES = 32


class WorkspaceIn(BaseModel):
    name: str = Name
    description: str | None = Field(default=None, max_length=2000)


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None
    created_at: dt.datetime


class ImportTable(BaseModel):
    schema_: str = Field(alias="schema", min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    target: str | None = Field(default=None, min_length=1, max_length=128)

    model_config = ConfigDict(populate_by_name=True)


class ImportSpec(BaseModel):
    connection_id: uuid.UUID
    tables: list[ImportTable] = Field(min_length=1, max_length=500)


class DatasetIn(BaseModel):
    name: str = Name
    description: str | None = Field(default=None, max_length=2000)
    import_spec: ImportSpec | None = None


class DatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    import_spec: ImportSpec | None = None


class DefinitionIn(BaseModel):
    model_version: int = Field(ge=1)
    definition: dict[str, Any]


class DefinitionOut(BaseModel):
    model_version: int
    definition: dict[str, Any] | None
    validation: dict[str, Any] | None = None


class DatasetOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    mode: str
    current_version: int
    model_version: int
    definition: dict[str, Any] | None
    created_at: dt.datetime
    updated_at: dt.datetime


class ConnectionIn(BaseModel):
    name: str = Name
    kind: str = Field(min_length=1, max_length=32)
    config: dict[str, Any]


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: dict[str, Any] | None = None


class ConnectionTestIn(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    config: dict[str, Any]


class RefreshOut(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    status: str
    trigger: str
    version: int | None
    created_at: dt.datetime
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    result: dict[str, Any] | None
    error: str | None


def jsonable(value: Any) -> Any:
    """Make a source value safe for JSON without losing meaning."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        raw = bytes(value)
        shown = raw[:MAX_BINARY_PREVIEW_BYTES].hex()
        more = "..." if len(raw) > MAX_BINARY_PREVIEW_BYTES else ""
        return f"0x{shown}{more}"
    return str(value)
