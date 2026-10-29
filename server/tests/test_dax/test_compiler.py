from __future__ import annotations

import datetime as dt

import duckdb
import pytest

from magbi.connectors.types import DataType
from magbi.dax.compiler import compile_measure
from magbi.dax.errors import DaxError
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


def _amounts() -> tuple[DatasetDefinition, duckdb.DuckDBPyConnection]:
    model = DatasetDefinition(
        tables=[
            TableDef(
                name="Sales",
                columns=[
                    ColumnDef(name="Amount", data_type=DataType.DECIMAL),
                    ColumnDef(name="Qty", data_type=DataType.INTEGER),
                ],
            ),
            TableDef(
                name="Other",
                columns=[ColumnDef(name="Amount", data_type=DataType.DECIMAL)],
            ),
        ]
    )
    con = duckdb.connect()
    con.execute('CREATE TABLE "Sales" ("Amount" DECIMAL(10, 2), "Qty" INTEGER)')
    con.execute('CREATE TABLE "Other" ("Amount" DECIMAL(10, 2))')
    return model, con


def test_divide_if_and_blank_arithmetic() -> None:
    model, con = _amounts()
    con.execute('INSERT INTO "Sales" VALUES (10, 0), (10, 0)')
    divided = compile_measure(model, "DIVIDE(SUM(Sales[Amount]), SUM(Sales[Qty]))")
    assert con.execute(divided).fetchone() == (None,)
    alt = compile_measure(model, "DIVIDE(SUM(Sales[Amount]), SUM(Sales[Qty]), 0)")
    assert con.execute(alt).fetchone() == (0,)
    flagged = compile_measure(model, "IF(SUM(Sales[Amount]) > 10, 1, 0)")
    assert con.execute(flagged).fetchone() == (1,)
    con.execute('DELETE FROM "Sales"')
    con.execute('INSERT INTO "Sales" VALUES (NULL, NULL), (NULL, NULL)')
    added = compile_measure(model, "SUM(Sales[Amount]) + 1")
    assert con.execute(added).fetchone() == (1,)


def test_calculate_replaces_a_filter() -> None:
    model = DatasetDefinition(
        tables=[
            TableDef(
                name="Sales",
                columns=[
                    ColumnDef(name="Amount", data_type=DataType.INTEGER),
                    ColumnDef(name="Status", data_type=DataType.STRING),
                ],
            ),
            TableDef(
                name="Other",
                columns=[
                    ColumnDef(
                        name="id",
                        data_type=DataType.INTEGER,
                        is_nullable=False,
                        is_primary_key=True,
                    ),
                    ColumnDef(name="Name", data_type=DataType.STRING),
                ],
            ),
        ]
    )
    con = duckdb.connect()
    con.execute('CREATE TABLE "Sales" ("Amount" INTEGER, "Status" VARCHAR)')
    con.execute(
        "INSERT INTO \"Sales\" VALUES (10, 'Completed'), (7, 'Open'), (3, 'Completed')"
    )
    done = compile_measure(
        model, 'CALCULATE(SUM(Sales[Amount]), Sales[Status] = "Completed")'
    )
    assert con.execute(done).fetchone() == (13,)
    replaced = compile_measure(
        model,
        'CALCULATE(SUM(Sales[Amount]), Sales[Status] = "Completed")',
        filters=(("Sales", "Status", "=", "Open"),),
    )
    assert con.execute(replaced).fetchone() == (13,)
    opened = compile_measure(
        model, "SUM(Sales[Amount])", filters=(("Sales", "Status", "=", "Open"),)
    )
    assert con.execute(opened).fetchone() == (7,)
    cleared = compile_measure(
        model,
        "CALCULATE(SUM(Sales[Amount]), ALL(Sales))",
        filters=(("Sales", "Status", "=", "Open"),),
    )
    assert con.execute(cleared).fetchone() == (20,)
    added = compile_measure(
        model,
        'CALCULATE(SUM(Sales[Amount]), FILTER(Sales, Sales[Status] = "Completed"))',
    )
    assert con.execute(added).fetchone() == (13,)
    with pytest.raises(DaxError, match="no relationship"):
        compile_measure(model, 'CALCULATE(SUM(Sales[Amount]), Other[Name] = "A")')


def test_an_ambiguous_filter_path_is_rejected() -> None:
    def key(name: str = "id") -> ColumnDef:
        return ColumnDef(
            name=name,
            data_type=DataType.INTEGER,
            is_nullable=False,
            is_primary_key=True,
        )

    model = DatasetDefinition(
        tables=[
            TableDef(
                name="Sales",
                columns=[
                    ColumnDef(name="Amount", data_type=DataType.INTEGER),
                    ColumnDef(name="a_id", data_type=DataType.INTEGER),
                    ColumnDef(name="b_id", data_type=DataType.INTEGER),
                ],
            ),
            TableDef(
                name="A",
                columns=[
                    key(),
                    ColumnDef(name="region_id", data_type=DataType.INTEGER),
                ],
            ),
            TableDef(
                name="B",
                columns=[
                    key(),
                    ColumnDef(name="region_id", data_type=DataType.INTEGER),
                ],
            ),
            TableDef(
                name="Region",
                columns=[key(), ColumnDef(name="Name", data_type=DataType.STRING)],
            ),
        ],
        relationships=[
            RelationshipDef.model_validate(
                {
                    "from": {"table": "Sales", "column": "a_id"},
                    "to": {"table": "A", "column": "id"},
                    "cardinality": "many-to-one",
                }
            ),
            RelationshipDef.model_validate(
                {
                    "from": {"table": "Sales", "column": "b_id"},
                    "to": {"table": "B", "column": "id"},
                    "cardinality": "many-to-one",
                }
            ),
            RelationshipDef.model_validate(
                {
                    "from": {"table": "A", "column": "region_id"},
                    "to": {"table": "Region", "column": "id"},
                    "cardinality": "many-to-one",
                }
            ),
            RelationshipDef.model_validate(
                {
                    "from": {"table": "B", "column": "region_id"},
                    "to": {"table": "Region", "column": "id"},
                    "cardinality": "many-to-one",
                }
            ),
        ],
    )
    with pytest.raises(DaxError, match="ambiguous"):
        compile_measure(model, 'CALCULATE(SUM(Sales[Amount]), Region[Name] = "East")')


def test_time_intelligence_shifts_the_date_filter() -> None:
    day = dt.date(2024, 3, 15)
    model = DatasetDefinition(
        tables=[
            TableDef(
                name="Sales",
                columns=[
                    ColumnDef(name="Amount", data_type=DataType.INTEGER),
                    ColumnDef(name="sold", data_type=DataType.DATE),
                ],
            ),
            TableDef(
                name="Date",
                is_date_table=True,
                date_column="Date",
                columns=[
                    ColumnDef(
                        name="Date",
                        data_type=DataType.DATE,
                        is_nullable=False,
                        is_primary_key=True,
                    )
                ],
            ),
        ],
        relationships=[
            RelationshipDef.model_validate(
                {
                    "from": {"table": "Sales", "column": "sold"},
                    "to": {"table": "Date", "column": "Date"},
                    "cardinality": "many-to-one",
                }
            )
        ],
        date_table={"fiscal_year_start_month": 7},
    )
    con = duckdb.connect()
    con.execute('CREATE TABLE "Sales" ("Amount" INTEGER, "sold" DATE)')
    con.execute('CREATE TABLE "Date" ("Date" DATE)')
    con.execute(
        'INSERT INTO "Sales" VALUES '
        "(10, DATE '2024-03-15'), (4, DATE '2023-03-15'), "
        "(8, DATE '2024-02-15'), (6, DATE '2023-08-01'), (100, DATE '2023-06-01')"
    )
    con.execute(
        'INSERT INTO "Date" VALUES '
        "(DATE '2024-03-15'), (DATE '2023-03-15'), (DATE '2024-02-15'), "
        "(DATE '2023-08-01'), (DATE '2023-06-01')"
    )
    filters = (("Date", "Date", "=", day),)
    last_year = compile_measure(
        model,
        "CALCULATE(SUM(Sales[Amount]), SAMEPERIODLASTYEAR(Date[Date]))",
        filters=filters,
    )
    assert con.execute(last_year).fetchone() == (4,)
    previous = compile_measure(
        model,
        "CALCULATE(SUM(Sales[Amount]), DATEADD(Date[Date], -1, MONTH))",
        filters=filters,
    )
    assert con.execute(previous).fetchone() == (8,)
    ytd = compile_measure(
        model, "TOTALYTD(SUM(Sales[Amount]), Date[Date])", filters=filters
    )
    assert con.execute(ytd).fetchone() == (24,)
    plain = DatasetDefinition(
        tables=[
            TableDef(
                name="Sales",
                columns=[
                    ColumnDef(name="Amount", data_type=DataType.INTEGER),
                    ColumnDef(name="sold", data_type=DataType.DATE),
                ],
            ),
            TableDef(
                name="Date",
                columns=[
                    ColumnDef(
                        name="Date",
                        data_type=DataType.DATE,
                        is_nullable=False,
                        is_primary_key=True,
                    )
                ],
            ),
        ]
    )
    with pytest.raises(DaxError, match="marked date table"):
        compile_measure(
            plain,
            "CALCULATE(SUM(Sales[Amount]), SAMEPERIODLASTYEAR(Date[Date]))",
            filters=filters,
        )


def test_two_fact_tables_are_rejected() -> None:
    model, _con = _amounts()
    with pytest.raises(DaxError, match="two fact tables"):
        compile_measure(model, "SUM(Sales[Amount]) + SUM(Other[Amount])")
