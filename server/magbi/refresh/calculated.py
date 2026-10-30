"""Write scalar calculated columns onto a staging DuckDB file.

Expressions are the ones the DAX binder already accepts for a calculated
column. An aggregation is rejected. Columns that mention another calculated
column wait until that column exists.
"""

from __future__ import annotations

from magbi.connectors.types import DataType
from magbi.dax.compiler import compile_row_expression
from magbi.dax.errors import DaxError
from magbi.model.schema import CalculatedColumnDef, DatasetDefinition

_SQL_TYPE = {
    DataType.INTEGER: "BIGINT",
    DataType.DECIMAL: "DOUBLE",
    DataType.STRING: "VARCHAR",
    DataType.BOOLEAN: "BOOLEAN",
    DataType.DATE: "DATE",
    DataType.DATETIME: "TIMESTAMP",
}


def apply_calculated_columns(con: object, model: DatasetDefinition) -> None:
    """Add each calculated column. ``con`` is the staging DuckDB connection."""
    for table in model.tables:
        if not table.calculated_columns:
            continue
        _apply_table(con, model, table.name, list(table.calculated_columns))


def _apply_table(
    con: object,
    model: DatasetDefinition,
    table: str,
    columns: list[CalculatedColumnDef],
) -> None:
    names = {column.name for column in columns}
    pending = list(columns)
    guard = 0
    while pending:
        guard += 1
        if guard > len(columns) * len(columns) + 1:
            from magbi.refresh.orchestrator import RefreshSetupError

            raise RefreshSetupError(
                f"calculated columns on {table!r} have a circular dependency"
            )
        column = pending.pop(0)
        waiting = [
            name
            for name in names
            if name != column.name and f"[{name}]" in column.expression
        ]
        if any(name not in _present(con, table) for name in waiting):
            pending.append(column)
            continue
        _add(con, model, table, column)


def _present(con: object, table: str) -> set[str]:
    rows = con.execute(  # type: ignore[attr-defined]
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
        [table],
    ).fetchall()
    return {str(row[0]) for row in rows}


def _add(
    con: object, model: DatasetDefinition, table: str, column: CalculatedColumnDef
) -> None:
    try:
        expression = compile_row_expression(model, column.expression)
    except DaxError as exc:
        from magbi.refresh.orchestrator import RefreshSetupError

        raise RefreshSetupError(f"{column.name}: {exc}") from None
    sql_type = _SQL_TYPE.get(column.data_type, "VARCHAR")
    quoted_table = _quote(table)
    quoted_column = _quote(column.name)
    con.execute(  # type: ignore[attr-defined]
        f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_column} {sql_type}"
    )
    con.execute(  # type: ignore[attr-defined]
        f"UPDATE {quoted_table} SET {quoted_column} = {expression.sql(dialect='duckdb')}"
    )


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
