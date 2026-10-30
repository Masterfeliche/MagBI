"""Load a CSV or Excel file into a dataset without dropping existing tables.

Live DuckDB is copied into staging first, the new table is created there, and
the caller promotes. Replacing a table keeps its measures.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

from magbi.connectors.types import DataType
from magbi.model.schema import (
    AggregationType,
    ColumnDef,
    CsvSource,
    DatasetDefinition,
    TableDef,
)
from magbi.storage.duckdb_store import DuckDBStore

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_SUFFIXES = {".csv", ".xlsx"}
_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_INTEGER = {
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "INT",
    "BIGINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
}
_DECIMAL = {
    "FLOAT",
    "DOUBLE",
    "REAL",
    "DECIMAL",
    "NUMERIC",
    "HUGEINT",
    "UHUGEINT",
}


class FileImportError(Exception):
    """The file could not be loaded into DuckDB."""


def table_name_from_filename(filename: str) -> str:
    stem = Path(filename.replace("\\", "/")).name
    stem = Path(stem).stem
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_")
    if not cleaned:
        cleaned = "imported"
    if cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    return cleaned[:128]


def duckdb_to_data_type(raw: str) -> DataType:
    kind = raw.upper().split("(", 1)[0].strip()
    if kind in {"BOOLEAN", "BOOL"}:
        return DataType.BOOLEAN
    if kind in _INTEGER:
        return DataType.INTEGER
    if kind in _DECIMAL:
        return DataType.DECIMAL
    if kind == "DATE":
        return DataType.DATE
    if kind.startswith("TIMESTAMP") or kind == "DATETIME":
        return DataType.DATETIME
    if kind == "TIME":
        return DataType.TIME
    if kind in {"BLOB", "BYTEA"}:
        return DataType.BINARY
    return DataType.STRING


def merge_imported_table(
    model: DatasetDefinition, table: TableDef
) -> DatasetDefinition:
    old = model.table(table.name)
    if old is not None:
        column_names = {column.name for column in table.columns}
        date_column = old.date_column if old.date_column in column_names else None
        table = table.model_copy(
            update={
                "measures": old.measures,
                "calculated_columns": old.calculated_columns,
                "hierarchies": [
                    hierarchy
                    for hierarchy in old.hierarchies
                    if all(level.column in column_names for level in hierarchy.levels)
                ],
                "is_date_table": bool(old.is_date_table and date_column),
                "date_column": date_column if old.is_date_table else None,
            }
        )
    tables = [item for item in model.tables if item.name != table.name]
    tables.append(table)
    return model.model_copy(update={"tables": tables})


def table_from_columns(
    name: str, columns: list[ColumnDef], file_path: Path, suffix: str
) -> TableDef:
    source = None
    if suffix == ".csv":
        source = CsvSource(file_path=str(file_path), has_header=True)
    return TableDef(name=name, source=source, columns=columns)


def import_file_to_staging(
    store: DuckDBStore, dataset_id: str, file_path: Path, table_name: str
) -> list[ColumnDef]:
    if not _SAFE_NAME.match(table_name):
        raise FileImportError(f"invalid table name {table_name!r}")
    suffix = file_path.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise FileImportError("upload a .csv or .xlsx file")
    _seed_staging_from_live(store, dataset_id)
    con = store.open_staging(dataset_id)
    try:
        ident = _quote_ident(table_name)
        path = _sql_path(file_path)
        if suffix == ".xlsx":
            con.execute("INSTALL excel")
            con.execute("LOAD excel")
            con.execute(
                f"CREATE OR REPLACE TABLE {ident} AS "
                f"SELECT * FROM read_xlsx('{path}', header=true)"
            )
        else:
            con.execute(
                f"CREATE OR REPLACE TABLE {ident} AS "
                f"SELECT * FROM read_csv_auto('{path}', header=true)"
            )
        rows = con.execute(f"DESCRIBE {ident}").fetchall()
    except FileImportError:
        store.discard_staging(dataset_id)
        raise
    except Exception as exc:
        store.discard_staging(dataset_id)
        raise FileImportError(str(exc)) from exc
    finally:
        con.close()
    if not rows:
        store.discard_staging(dataset_id)
        raise FileImportError("file has no columns")
    return [_column_from_describe(row) for row in rows]


def _column_from_describe(row: tuple[object, ...]) -> ColumnDef:
    name = str(row[0])
    data_type = duckdb_to_data_type(str(row[1]))
    aggregation = (
        AggregationType.SUM
        if data_type in {DataType.INTEGER, DataType.DECIMAL}
        else None
    )
    return ColumnDef(
        name=name,
        data_type=data_type,
        is_nullable=True,
        source_column=name,
        default_aggregation=aggregation,
    )


def carry_over_tables(
    store: DuckDBStore,
    dataset_id: str,
    con: duckdb.DuckDBPyConnection,
    names: list[str],
) -> None:
    """Copy uploaded tables from the live file into a staging connection.

    Uploads have no source to re-read, so a refresh keeps the rows already loaded.
    """
    live = store.live_path(dataset_id)
    if not names or not live.is_file():
        return
    con.execute(f"ATTACH '{_sql_path(live)}' AS carry (READ_ONLY)")
    try:
        present = {
            str(row[0])
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_catalog = 'carry' AND table_type = 'BASE TABLE'"
            ).fetchall()
        }
        for name in names:
            if name in present:
                ident = _quote_ident(name)
                con.execute(
                    f"CREATE OR REPLACE TABLE {ident} AS SELECT * FROM carry.{ident}"
                )
    finally:
        con.execute("DETACH carry")


def _seed_staging_from_live(store: DuckDBStore, dataset_id: str) -> None:
    store.discard_staging(dataset_id)
    live = store.live_path(dataset_id)
    if not live.is_file():
        return
    con = store.open_staging(dataset_id)
    try:
        con.execute(f"ATTACH '{_sql_path(live)}' AS src (READ_ONLY)")
        tables = con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_catalog = 'src' AND table_type = 'BASE TABLE'"
        ).fetchall()
        for (name,) in tables:
            ident = _quote_ident(str(name))
            con.execute(
                f"CREATE OR REPLACE TABLE {ident} AS SELECT * FROM src.{ident}"
            )
        con.execute("DETACH src")
    except Exception as exc:
        con.close()
        store.discard_staging(dataset_id)
        raise FileImportError(str(exc)) from exc
    else:
        con.close()


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")
