from magbi.connectors.types import DataType
from magbi.engine.errors import QueryError
from magbi.engine.joins import join_steps
from tests.test_model.test_schema import col, definition, key, link, table


def test_a_dimension_is_joined_from_the_fact() -> None:
    model = definition(
        table("Sales", key(), col("dept_id"), col("Amount", DataType.INTEGER)),
        table("Department", key(), col("Name", DataType.STRING)),
        relationships=[link("Sales", "Department")],
    )
    steps = join_steps(model, "Sales", ("Department", "Sales"))
    assert [nxt for _rel, nxt in steps] == ["Department"]
    assert steps[0][0].join_type == "left"


def test_a_missing_or_ambiguous_path_is_an_error() -> None:
    missing = definition(
        table("Sales", key(), col("Amount", DataType.INTEGER)),
        table("Region", key()),
    )
    try:
        join_steps(missing, "Sales", ("Region",))
    except QueryError as exc:
        assert exc.code == "NO_RELATIONSHIP"
    else:
        raise AssertionError("expected NO_RELATIONSHIP")

    diamond = definition(
        table("Sales", key(), col("dept_id"), col("owner_id")),
        table("Department", key(), col("region_id")),
        table("Owner", key(), col("region_id")),
        table("Region", key()),
        relationships=[
            link("Sales", "Department"),
            link(
                "Sales", "Owner", **{"from": {"table": "Sales", "column": "owner_id"}}
            ),
            link(
                "Department",
                "Region",
                **{"from": {"table": "Department", "column": "region_id"}},
            ),
            link(
                "Owner", "Region", **{"from": {"table": "Owner", "column": "region_id"}}
            ),
        ],
    )
    try:
        join_steps(diamond, "Sales", ("Region",))
    except QueryError as exc:
        assert exc.code == "AMBIGUOUS_PATH"
    else:
        raise AssertionError("expected AMBIGUOUS_PATH")
