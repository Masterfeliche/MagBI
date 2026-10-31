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


def test_a_role_on_a_dimension_filters_its_facts() -> None:
    """Found end to end: the role's table was never joined, so DuckDB failed (500)."""
    from magbi.model.schema import RelationshipDef

    model = definition(
        table("Region", col("Region", DataType.STRING, is_primary_key=True)),
        table(
            "Sales",
            col("Amount", DataType.INTEGER),
            col("Region", DataType.STRING),
            measures=[MeasureDef(name="Total", expression="SUM(Sales[Amount])")],
        ),
        table("Notes", col("Text", DataType.STRING), measures=[MeasureDef(name="Notes", expression="COUNTROWS(Notes)")]),
        relationships=[
            RelationshipDef.model_validate(
                {"from": {"table": "Sales", "column": "Region"}, "to": {"table": "Region", "column": "Region"}, "cardinality": "many-to-one"}
            )
        ],
        roles=[RlsRoleDef(name="North", table_filters=[RlsTableFilter(table="Region", expression='Region[Region] = "North"')])],
    )
    con = duckdb.connect()
    con.execute('CREATE TABLE "Region" ("Region" VARCHAR)')
    con.execute("INSERT INTO \"Region\" VALUES ('North'), ('South')")
    con.execute('CREATE TABLE "Sales" ("Amount" INTEGER, "Region" VARCHAR)')
    con.execute("INSERT INTO \"Sales\" VALUES (5, 'North'), (9, 'South'), (1, 'North')")
    con.execute('CREATE TABLE "Notes" ("Text" VARCHAR)')
    con.execute("INSERT INTO \"Notes\" VALUES ('a'), ('b')")
    total = parse_query({"select": [{"measure": {"table": "Sales", "measure": "Total"}}]})
    by_region = parse_query(
        {"select": [{"column": {"table": "Region", "column": "Region"}}, {"measure": {"table": "Sales", "measure": "Total"}}]}
    )
    notes = parse_query({"select": [{"measure": {"table": "Notes", "measure": "Notes"}}]})
    assert run_query(model, total, con, roles=("North",))["rows"] == [[6]]  # type: ignore[arg-type]
    assert run_query(model, by_region, con, roles=("North",))["rows"] == [["North", 6]]  # type: ignore[arg-type]
    # A table the role's filter cannot reach is not filtered, as in Power BI.
    assert run_query(model, notes, con, roles=("North",))["rows"] == [[2]]  # type: ignore[arg-type]


def test_a_rule_may_name_its_own_table_columns_without_the_table() -> None:
    """As in Power BI: a rule on Region may say [Region] = "North"; a measure keeps its meaning."""
    from magbi.dax.parser import ColumnRef as Col
    from magbi.engine.rls import bind_rule

    model = definition(
        table("Region", col("Region", DataType.STRING), measures=[MeasureDef(name="Regions", expression="COUNTROWS(Region)")]),
        table("Sales", col("Amount", DataType.INTEGER), measures=[MeasureDef(name="Total", expression="SUM(Sales[Amount])")]),
        roles=[RlsRoleDef(name="Short", table_filters=[RlsTableFilter(table="Region", expression='[region] = "North"')])],
    )
    bound = bind_rule(model, "Region", '[region] = "North"')
    assert isinstance(bound.left, Col) and (bound.left.table, bound.left.column) == ("Region", "Region")  # type: ignore[attr-defined]
    # [Total] is a measure, not a Region column, so it is left for the binder (which expands it).
    assert not isinstance(bind_rule(model, "Region", "[Total] > 1").left, Col)  # type: ignore[attr-defined]

    con = duckdb.connect()
    con.execute('CREATE TABLE "Region" ("Region" VARCHAR)')
    con.execute("INSERT INTO \"Region\" VALUES ('North'), ('South')")
    con.execute('CREATE TABLE "Sales" ("Amount" INTEGER)')
    query = parse_query({"select": [{"measure": {"table": "Region", "measure": "Regions"}}]})
    assert run_query(model, query, con, roles=("Short",))["rows"] == [[1]]  # type: ignore[arg-type]
