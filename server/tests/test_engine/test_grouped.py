import duckdb

from magbi.connectors.types import DataType
from magbi.engine.filter_context import bind_filters
from magbi.engine.semantic import bind_query, parse_query
from magbi.engine.sql_gen import detail_sql
from magbi.model.schema import MeasureDef
from tests.test_model.test_schema import col, definition, table


def _sales() -> object:
    return definition(
        table(
            "Sales",
            col("Amount", DataType.INTEGER),
            col("Status", DataType.STRING),
            measures=[
                MeasureDef(
                    name="Completed",
                    expression='CALCULATE(SUM(Sales[Amount]), Sales[Status] = "Completed")',
                )
            ],
        )
    )


def test_calculate_replaces_the_query_filter_and_order_limits_rows() -> None:
    model = _sales()
    replaced = parse_query(
        {
            "select": [
                {"measure": {"table": "Sales", "measure": "Completed"}},
            ],
            "where": [
                {
                    "column": {"table": "Sales", "column": "Status"},
                    "operator": "eq",
                    "values": ["Open"],
                }
            ],
        }
    )
    bound = bind_query(model, replaced)  # type: ignore[arg-type]
    filters = bind_filters(model, replaced)  # type: ignore[arg-type]
    sql = detail_sql(model, bound, filters)  # type: ignore[arg-type]
    con = duckdb.connect()
    con.execute('CREATE TABLE "Sales" ("Amount" INTEGER, "Status" VARCHAR)')
    con.execute("INSERT INTO \"Sales\" VALUES (7, 'Open'), (13, 'Completed')")
    assert con.execute(sql).fetchone() == (13,)

    ranked = parse_query(
        {
            "select": [
                {"column": {"table": "Sales", "column": "Status"}},
                {
                    "column": {"table": "Sales", "column": "Amount"},
                    "aggregation": "sum",
                },
            ],
            "orderBy": [{"select": 1, "direction": "desc"}],
            "limit": 1,
        }
    )
    ranked_bound = bind_query(model, ranked)  # type: ignore[arg-type]
    ranked_sql = detail_sql(model, ranked_bound)  # type: ignore[arg-type]
    assert con.execute(ranked_sql).fetchone() == ("Completed", 13)
