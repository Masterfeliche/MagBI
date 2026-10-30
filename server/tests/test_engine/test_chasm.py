import duckdb

from magbi.connectors.types import DataType
from magbi.engine.semantic import bind_query, parse_query
from magbi.engine.sql_gen import detail_sql
from magbi.model.schema import MeasureDef
from tests.test_model.test_schema import col, definition, key, link, table


def _model() -> object:
    product = table("Product", key(), col("Category", DataType.STRING))
    sales = table(
        "Sales",
        key(),
        col("product_id"),
        col("Amount", DataType.INTEGER),
        measures=[MeasureDef(name="Revenue", expression="SUM(Sales[Amount])")],
    )
    costs = table(
        "Costs",
        key(),
        col("product_id"),
        col("Amount", DataType.INTEGER),
        measures=[MeasureDef(name="Spend", expression="SUM(Costs[Amount])")],
    )
    return definition(
        product,
        sales,
        costs,
        relationships=[
            link(
                "Sales",
                "Product",
                **{"from": {"table": "Sales", "column": "product_id"}},
            ),
            link(
                "Costs",
                "Product",
                **{"from": {"table": "Costs", "column": "product_id"}},
            ),
        ],
    )


def test_two_facts_do_not_inflate_each_other() -> None:
    model = _model()
    query = parse_query(
        {
            "select": [
                {"column": {"table": "Product", "column": "Category"}},
                {"measure": {"table": "Sales", "measure": "Revenue"}},
                {"measure": {"table": "Costs", "measure": "Spend"}},
            ]
        }
    )
    bound = bind_query(model, query)  # type: ignore[arg-type]
    sql = detail_sql(model, bound)  # type: ignore[arg-type]
    assert "FULL" in sql and "JOIN" in sql
    con = duckdb.connect()
    con.execute('CREATE TABLE "Product" ("id" INTEGER, "Category" VARCHAR)')
    con.execute(
        'CREATE TABLE "Sales" ("id" INTEGER, "product_id" INTEGER, "Amount" INTEGER)'
    )
    con.execute(
        'CREATE TABLE "Costs" ("id" INTEGER, "product_id" INTEGER, "Amount" INTEGER)'
    )
    con.execute("INSERT INTO \"Product\" VALUES (1, 'Electronics'), (2, 'Clothing')")
    con.execute('INSERT INTO "Sales" VALUES (1, 1, 10), (2, 1, 5), (3, 2, 7)')
    con.execute('INSERT INTO "Costs" VALUES (1, 1, 4), (2, 2, 1), (3, 2, 1)')
    rows = sorted(con.execute(sql).fetchall())
    assert rows == [("Clothing", 7, 2), ("Electronics", 15, 4)]
