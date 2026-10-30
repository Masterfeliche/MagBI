"""Per-table import pipeline: connector rows -> Arrow batches -> staging DuckDB.

Memory stays flat: rows are pulled from the connector in batches (default
10,000), converted to one Arrow table each and inserted into the staging file.
There is no Parquet intermediate yet (see MAGBI-002 design decision 5); the
batching lives in ``_import_table`` so one can be added if profiling asks.

Tables are imported one after another because DuckDB has a single writer.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import duckdb
import pyarrow as pa

from magbi.connectors.base import Connector
from magbi.connectors.types import (
    DataType,
    TypePlan,
    arrow_schema,
    cast_map,
    plan_columns,
    warnings,
)

DEFAULT_BATCH_SIZE = 10_000
MAX_TARGET_LENGTH = 128
_BATCH_VIEW = "_magbi_batch"

ProgressCallback = Callable[[str, int], None]
"""Called after every batch with ``(target table, rows imported so far)``."""


class ImportPipelineError(Exception):
    """A table could not be imported. The message is safe to show to users."""


@dataclass(frozen=True)
class TableSpec:
    schema: str
    name: str
    target: str


@dataclass
class TableResult:
    schema: str
    name: str
    target: str
    rows: int
    seconds: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImportResult:
    tables: list[TableResult] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return sum(t.rows for t in self.tables)

    @property
    def warnings(self) -> list[str]:
        return [w for t in self.tables for w in t.warnings]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "warnings": self.warnings,
            "tables": [
                {
                    "schema": t.schema,
                    "name": t.name,
                    "target": t.target,
                    "rows": t.rows,
                    "seconds": round(t.seconds, 3),
                    "warnings": t.warnings,
                }
                for t in self.tables
            ],
        }


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def validate_target(target: str) -> None:
    if not target or len(target) > MAX_TARGET_LENGTH:
        raise ImportPipelineError(
            f"target table name must be 1-{MAX_TARGET_LENGTH} characters"
        )
    if any(ord(ch) < 32 for ch in target):
        raise ImportPipelineError("target table name contains control characters")


def _coercer(plan: TypePlan) -> Callable[[Any], Any] | None:
    # DECIMAL beyond DuckDB's 38 digits is imported as double; pyodbc yields Decimal.
    if plan.data_type is DataType.DECIMAL and plan.arrow_type == pa.float64():
        return lambda v: (
            None if v is None else float(v) if isinstance(v, Decimal) else v
        )
    return None


def _batches(
    rows: Iterator[tuple[Any, ...]], size: int
) -> Iterator[list[tuple[Any, ...]]]:
    while chunk := list(itertools.islice(rows, size)):
        yield chunk


def _to_arrow(
    chunk: list[tuple[Any, ...]],
    schema: pa.Schema,
    coercers: list[Callable[[Any], Any] | None],
) -> pa.Table:
    arrays = []
    for i, field_ in enumerate(schema):
        values = [row[i] for row in chunk]
        fn = coercers[i]
        if fn is not None:
            values = [fn(v) for v in values]
        arrays.append(pa.array(values, type=field_.type))
    return pa.Table.from_arrays(arrays, schema=schema)


def _import_table(
    connector: Connector,
    spec: TableSpec,
    staging: duckdb.DuckDBPyConnection,
    batch_size: int,
    progress: ProgressCallback | None,
) -> TableResult:
    started = time.perf_counter()
    source = connector.find_table(spec.schema, spec.name)  # must exist in the catalog
    if not source.columns:
        raise ImportPipelineError(f"{source.qualified_name} has no readable columns")
    plans = plan_columns(source.columns)
    schema = arrow_schema(plans)
    coercers = [_coercer(p) for p in plans]
    result_warnings = warnings(plans)

    expected = connector.get_row_count(spec.schema, spec.name)
    target = quote_ident(spec.target)
    columns_sql = ", ".join(f"{quote_ident(p.column)} {p.duckdb_type}" for p in plans)
    staging.execute(f"CREATE OR REPLACE TABLE {target} ({columns_sql})")

    sql = connector.build_select(source, casts=cast_map(plans))
    imported = 0
    for chunk in _batches(
        connector.execute_query(sql, batch_size=batch_size), batch_size
    ):
        try:
            batch = _to_arrow(chunk, schema, coercers)
        except (pa.ArrowException, ValueError, TypeError, OverflowError) as exc:
            raise ImportPipelineError(
                f"{source.qualified_name}: a value could not be converted "
                f"({type(exc).__name__}) near row {imported + 1}"
            ) from exc
        staging.register(_BATCH_VIEW, batch)
        try:
            staging.execute(f"INSERT INTO {target} SELECT * FROM {_BATCH_VIEW}")
        finally:
            staging.unregister(_BATCH_VIEW)
        imported += len(chunk)
        if progress is not None:
            progress(spec.target, imported)

    stored_row = staging.execute(f"SELECT count(*) FROM {target}").fetchone()
    stored = int(stored_row[0]) if stored_row else -1
    if stored != imported:
        raise ImportPipelineError(
            f"{source.qualified_name}: wrote {stored} rows but read {imported}"
        )
    if imported != expected:
        # The source is a live system; rows may be added or removed mid-import.
        result_warnings.append(
            f"{source.qualified_name}: source row count changed during import "
            f"(counted {expected} before, imported {imported})"
        )
    return TableResult(
        schema=spec.schema,
        name=spec.name,
        target=spec.target,
        rows=imported,
        seconds=time.perf_counter() - started,
        warnings=result_warnings,
    )


def import_tables(
    connector: Connector,
    tables: Sequence[TableSpec],
    staging: duckdb.DuckDBPyConnection,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress: ProgressCallback | None = None,
) -> ImportResult:
    """Import ``tables`` into ``staging``. The connector must already be connected.

    Raises ``ImportPipelineError`` (bad spec or unconvertible data) or
    ``ConnectorError`` (source problems); the staging file is then incomplete and
    the caller must discard it.
    """
    if not tables:
        raise ImportPipelineError("nothing to import: no tables selected")
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    seen: set[str] = set()
    for spec in tables:
        validate_target(spec.target)
        key = spec.target.lower()
        if key in seen:
            raise ImportPipelineError(f"duplicate target table name {spec.target!r}")
        seen.add(key)

    result = ImportResult()
    for spec in tables:
        result.tables.append(
            _import_table(connector, spec, staging, batch_size, progress)
        )
    return result
