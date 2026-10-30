import datetime as dt

import duckdb

from magbi.connectors.types import DataType
from magbi.engine.executor import run_query
from magbi.engine.semantic import parse_query
from magbi.model.schema import MeasureDef
from tests.test_model.test_schema import col, definition, table


def test_blank_rows_drop_and_totals_ignore_the_grouping() -> None:
    model = definition(
        table(
            "Sales",
            col("Amount", DataType.INTEGER),
            col("Status", DataType.STRING),
            col("sold", DataType.DATE),
            measures=[
                MeasureDef(
                    name="Revenue",
                    expression="SUM(Sales[Amount])",
                    format="#,##0",
                )
            ],
        )
    )
    con = duckdb.connect()
    con.execute(
        'CREATE TABLE "Sales" ("Amount" INTEGER, "Status" VARCHAR, "sold" DATE)'
    )
    con.execute(
        "INSERT INTO \"Sales\" VALUES (5, 'Open', DATE '2024-03-15'), "
        "(NULL, 'Empty', DATE '2024-03-16'), (8, 'Open', DATE '2024-03-15')"
    )
    query = parse_query(
        {
            "select": [
                {"column": {"table": "Sales", "column": "sold"}},
                {"measure": {"table": "Sales", "measure": "Revenue"}},
            ],
            "includeTotals": True,
            "limit": 10,
        }
    )
    result = run_query(model, query, con)
    assert result["truncated"] is False
    assert result["rows"] == [[dt.date(2024, 3, 15).isoformat(), 13]]
    assert result["rowCount"] == 1
    assert result["totals"] == [None, 13]
    columns = result["columns"]
    assert isinstance(columns, list)
    assert columns[1]["isMeasure"] is True and columns[1]["format"] == "#,##0"


def test_a_full_limit_is_truncated() -> None:
    model = definition(
        table(
            "Sales",
            col("Status", DataType.STRING),
            col("Amount", DataType.INTEGER),
        )
    )
    con = duckdb.connect()
    con.execute('CREATE TABLE "Sales" ("Status" VARCHAR, "Amount" INTEGER)')
    con.execute("INSERT INTO \"Sales\" VALUES ('A', 1), ('B', 2), ('C', 3)")
    query = parse_query(
        {
            "select": [
                {"column": {"table": "Sales", "column": "Status"}},
                {
                    "column": {"table": "Sales", "column": "Amount"},
                    "aggregation": "sum",
                },
            ],
            "limit": 2,
        }
    )
    result = run_query(model, query, con)
    assert result["truncated"] is True
    assert result["rowCount"] == 2
