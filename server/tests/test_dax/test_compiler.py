from __future__ import annotations

import duckdb

from magbi.connectors.types import DataType
from magbi.dax.compiler import compile_measure
from magbi.model.schema import ColumnDef, DatasetDefinition, RelationshipDef, TableDef


def _model() -> DatasetDefinition:
    return DatasetDefinition(
        tables=[
            TableDef(
                name="Sales",
                columns=[
                    ColumnDef(name="Amount", data_type=DataType.DECIMAL),
                    ColumnDef(name="dept_id", data_type=DataType.INTEGER),
                ],
            ),
            TableDef(
                name="Department",
                columns=[
                    ColumnDef(
                        name="id",
                        data_type=DataType.INTEGER,
                        is_nullable=False,
                        is_primary_key=True,
                    )
                ],
            ),
        ],
        relationships=[
            RelationshipDef.model_validate(
                {
                    "from": {"table": "Sales", "column": "dept_id"},
                    "to": {"table": "Department", "column": "id"},
                    "cardinality": "many-to-one",
                }
            )
        ],
    )


def _db() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute('CREATE TABLE "Sales" ("Amount" DECIMAL(10, 2), "dept_id" INTEGER)')
    con.execute('CREATE TABLE "Department" ("id" INTEGER)')
    con.execute('INSERT INTO "Sales" VALUES (10, 1), (NULL, 1), (5, 1), (5, 1)')
    con.execute('INSERT INTO "Department" VALUES (1)')
    return con


def test_each_aggregate_runs_on_duckdb() -> None:
    model = _model()
    con = _db()
    expected = {
        "SUM(Sales[Amount])": 20,
        "COUNT(Sales[Amount])": 3,
        "COUNTA(Sales[Amount])": 3,
        "COUNTROWS(Sales)": 4,
        "AVERAGE(Sales[Amount])": 20 / 3,
        "MIN(Sales[Amount])": 5,
        "MAX(Sales[Amount])": 10,
        "DISTINCTCOUNT(Sales[Amount])": 2,
    }
    for source, value in expected.items():
        sql = compile_measure(model, source)
        got = con.execute(sql).fetchone()
        assert got is not None
        assert float(got[0]) == value


def test_a_related_table_is_joined() -> None:
    sql = compile_measure(_model(), "SUM(Sales[Amount])", also=("Department",))
    assert 'JOIN "Department"' in sql
    assert '"Sales"."dept_id" = "Department"."id"' in sql
    con = _db()
    got = con.execute(sql).fetchone()
    assert got is not None and float(got[0]) == 20
