import duckdb

from magbi.connectors.types import DataType
from magbi.engine.errors import QueryError
from magbi.engine.executor import run_query
from magbi.engine.rls import role_filters
from magbi.engine.semantic import parse_query
from magbi.model.schema import MeasureDef, RlsRoleDef, RlsTableFilter
from tests.test_model.test_schema import col, definition, table


def _model() -> object:
    return definition(
        table(
            "Sales",
            col("Amount", DataType.INTEGER),
            col("Dept", DataType.STRING),
            measures=[
                MeasureDef(
                    name="AllSales",
                    expression="CALCULATE(SUM(Sales[Amount]), ALL(Sales))",
                )
            ],
        ),
        roles=[
            RlsRoleDef(
                name="DepartmentAccess",
                table_filters=[
                    RlsTableFilter(table="Sales", expression='Sales[Dept] = "Finance"')
                ],
            )
        ],
    )


def test_all_does_not_remove_a_role_filter() -> None:
    model = _model()
    con = duckdb.connect()
    con.execute('CREATE TABLE "Sales" ("Amount" INTEGER, "Dept" VARCHAR)')
    con.execute("INSERT INTO \"Sales\" VALUES (5, 'Finance'), (9, 'Other')")
    query = parse_query(
        {"select": [{"measure": {"table": "Sales", "measure": "AllSales"}}]}
    )
    open_result = run_query(model, query, con)  # type: ignore[arg-type]
    secured = run_query(model, query, con, roles=("DepartmentAccess",))  # type: ignore[arg-type]
    assert open_result["rows"] == [[14]]
    assert secured["rows"] == [[5]]


def test_an_unknown_role_and_a_non_comparison_are_rejected() -> None:
    model = _model()
    query = parse_query(
        {"select": [{"measure": {"table": "Sales", "measure": "AllSales"}}]}
    )
    try:
        run_query(model, query, None, roles=("Missing",))  # type: ignore[arg-type]
    except QueryError as exc:
        assert exc.code == "UNKNOWN_ROLE"
    else:
        raise AssertionError("expected UNKNOWN_ROLE")

    broken = definition(
        table("Sales", col("Amount", DataType.INTEGER)),
        roles=[
            RlsRoleDef(
                name="Bad",
                table_filters=[
                    RlsTableFilter(table="Sales", expression="SUM(Sales[Amount])")
                ],
            )
        ],
    )
    try:
        role_filters(broken, ("Bad",))
    except QueryError as exc:
        assert exc.code == "RLS_FILTER"
    else:
        raise AssertionError("expected RLS_FILTER")
