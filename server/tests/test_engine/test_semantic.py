from magbi.connectors.types import DataType
from magbi.engine.errors import QueryError
from magbi.engine.semantic import bind_query, parse_query
from magbi.model.schema import MeasureDef
from tests.test_model.test_schema import col, definition, table


def _model() -> object:
    return definition(
        table(
            "Sales",
            col("Amount", DataType.INTEGER),
            col("Status", DataType.STRING),
            measures=[MeasureDef(name="Revenue", expression="SUM(Sales[Amount])")],
        )
    )


def test_a_measure_and_a_column_bind() -> None:
    query = parse_query(
        {
            "from": [{"table": "sales"}],
            "select": [
                {"column": {"table": "Sales", "column": "Status"}},
                {"measure": {"table": "Sales", "measure": "revenue"}, "as": "Revenue"},
            ],
        }
    )
    bound = bind_query(_model(), query)  # type: ignore[arg-type]
    assert bound.sources == ("Sales",)
    assert bound.groups[0].column == "Status" and bound.groups[0].alias == "Status"
    assert bound.measures[0].expression == "SUM(Sales[Amount])"
    assert bound.measures[0].alias == "Revenue"


def test_an_aggregation_becomes_a_measure_expression() -> None:
    query = parse_query(
        {
            "select": [
                {
                    "column": {"table": "Sales", "column": "Amount"},
                    "aggregation": "sum",
                }
            ]
        }
    )
    bound = bind_query(_model(), query)  # type: ignore[arg-type]
    assert bound.groups == ()
    assert bound.measures[0].expression == "SUM(Sales[Amount])"
    assert bound.measures[0].data_type == DataType.INTEGER


def test_unknown_names_and_a_bad_select_are_rejected() -> None:
    model = _model()
    missing = parse_query(
        {"select": [{"column": {"table": "Sales", "column": "Nope"}}]}
    )
    try:
        bind_query(model, missing)  # type: ignore[arg-type]
    except QueryError as exc:
        assert exc.code == "UNKNOWN_COLUMN"
    else:
        raise AssertionError("expected UNKNOWN_COLUMN")

    try:
        parse_query(
            {
                "select": [
                    {
                        "column": {"table": "Sales", "column": "Amount"},
                        "measure": {"table": "Sales", "measure": "Revenue"},
                    }
                ]
            }
        )
    except QueryError as exc:
        assert exc.code == "QUERY_SHAPE"
    else:
        raise AssertionError("expected QUERY_SHAPE")
