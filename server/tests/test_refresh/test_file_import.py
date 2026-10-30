from pathlib import Path

import duckdb
import pytest

from magbi.connectors.types import DataType
from magbi.model.schema import ColumnDef, DatasetDefinition, MeasureDef, TableDef
from magbi.refresh.file_import import (
    FileImportError,
    duckdb_to_data_type,
    import_file_to_staging,
    merge_imported_table,
    table_name_from_filename,
)
from magbi.storage.duckdb_store import DuckDBStore

DS = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture
def store(tmp_path: Path) -> DuckDBStore:
    return DuckDBStore(tmp_path / "datasets")


def test_table_name_from_filename() -> None:
    assert table_name_from_filename("General-Ledger.xlsx") == "General_Ledger"
    assert table_name_from_filename("sales.csv") == "sales"
    assert table_name_from_filename("2024-actuals.csv") == "t_2024_actuals"
    assert table_name_from_filename(r"C:\tmp\Ledger.csv") == "Ledger"


def test_duckdb_type_map() -> None:
    assert duckdb_to_data_type("BIGINT") is DataType.INTEGER
    assert duckdb_to_data_type("DECIMAL(18,2)") is DataType.DECIMAL
    assert duckdb_to_data_type("VARCHAR") is DataType.STRING
    assert duckdb_to_data_type("TIMESTAMP WITH TIME ZONE") is DataType.DATETIME


def test_merge_keeps_measures() -> None:
    model = DatasetDefinition(
        tables=[
            TableDef(
                name="sales",
                columns=[ColumnDef(name="Amount", data_type=DataType.INTEGER)],
                measures=[MeasureDef(name="Total", expression="SUM(sales[Amount])")],
            )
        ]
    )
    updated = merge_imported_table(
        model,
        TableDef(
            name="sales",
            columns=[
                ColumnDef(name="Amount", data_type=DataType.INTEGER),
                ColumnDef(name="Region", data_type=DataType.STRING),
            ],
        ),
    )
    table = updated.table("sales")
    assert table is not None
    assert [c.name for c in table.columns] == ["Amount", "Region"]
    assert table.measures[0].name == "Total"


def test_csv_lands_in_staging_and_keeps_existing_tables(
    store: DuckDBStore, tmp_path: Path
) -> None:
    live = store.live_path(DS)
    live.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(live))
    con.execute('CREATE TABLE "Ledger" AS SELECT 1 AS id, 10.5 AS Credit')
    con.close()

    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("Region,Amount\nEast,10\nWest,20\n", encoding="utf-8")
    columns = import_file_to_staging(store, DS, csv_path, "sales")
    names = {column.name: column.data_type for column in columns}
    assert names["Region"] is DataType.STRING
    assert names["Amount"] in {DataType.INTEGER, DataType.DECIMAL}

    store.promote_staging(DS)
    live_con = store.open_live(DS)
    try:
        tables = {
            row[0]
            for row in live_con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
        assert "Ledger" in tables
        assert "sales" in tables
        total = live_con.execute("SELECT sum(Amount) FROM sales").fetchone()
        assert total is not None
        assert int(total[0]) == 30
        credit = live_con.execute("SELECT Credit FROM Ledger").fetchone()
        assert credit is not None
        assert float(credit[0]) == 10.5
    finally:
        live_con.close()


def test_rejects_unknown_suffix(store: DuckDBStore, tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("nope", encoding="utf-8")
    with pytest.raises(FileImportError):
        import_file_to_staging(store, DS, path, "notes")
