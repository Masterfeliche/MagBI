import datetime as dt

import duckdb

from magbi.connectors.types import DataType
from magbi.dax.compiler import compile_measure
from magbi.engine.errors import QueryError
from magbi.engine.filter_context import bind_filters
from magbi.engine.semantic import parse_query
from tests.test_model.test_schema import col, definition, table


def _model() -> object:
    return definition(
        table(
            "Sales",
            col("Amount", DataType.INTEGER),
            col("Status", DataType.STRING),
            col("sold", DataType.DATE),
        )
    )


def test_where_becomes_compiler_filters() -> None:
    query = parse_query(
        {
            "select": [
                {"column": {"table": "Sales", "column": "Amount"}, "aggregation": "sum"}
            ],
            "where": [
                {
                    "column": {"table": "Sales", "column": "Status"},
                    "operator": "contains",
                    "values": ["Op%en"],
                },
                {
                    "column": {"table": "Sales", "column": "sold"},
                    "operator": "eq",
                    "values": ["2024-03-15"],
                },
            ],
        }
    )
    filters = bind_filters(_model(), query)  # type: ignore[arg-type]
    assert filters[0].op == "contains" and filters[0].value == "Op%en"
    assert filters[1].value == dt.date(2024, 3, 15)
    sql = compile_measure(
        _model(),  # type: ignore[arg-type]
        "SUM(Sales[Amount])",
        filters=tuple(item.as_tuple() for item in filters),
    )
    assert "CONTAINS(" in sql
    con = duckdb.connect()
    con.execute(
        'CREATE TABLE "Sales" ("Amount" INTEGER, "Status" VARCHAR, "sold" DATE)'
    )
    con.execute(
        "INSERT INTO \"Sales\" VALUES (5, 'Op%en', DATE '2024-03-15'), (9, 'Open', DATE '2024-03-15')"
    )
    assert con.execute(sql).fetchone() == (5,)


def test_a_blank_filter_rejects_a_value() -> None:
    query = parse_query(
        {
            "select": [
                {"column": {"table": "Sales", "column": "Amount"}, "aggregation": "sum"}
            ],
            "where": [
                {
                    "column": {"table": "Sales", "column": "Status"},
                    "operator": "isBlank",
                    "values": ["x"],
                }
            ],
        }
    )
    try:
        bind_filters(_model(), query)  # type: ignore[arg-type]
    except QueryError as exc:
        assert exc.code == "BAD_FILTER"
    else:
        raise AssertionError("expected BAD_FILTER")
