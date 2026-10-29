import pytest

from magbi.model.relationships import find_cycle, join_path
from magbi.model.schema import ModelSchemaError, RelationshipDef
from tests.test_model.test_schema import col, definition, key, table


def rel(
    frm: str, column: str, to: str, *, active: bool = True, to_column: str = "id"
) -> RelationshipDef:
    return RelationshipDef.model_validate(
        {
            "from": {"table": frm, "column": column},
            "to": {"table": to, "column": to_column},
            "cardinality": "many-to-one",
            "is_active": active,
        }
    )


def chain():
    return definition(
        table("Invoices", key(), col("dept_id")),
        table("Department", key(), col("region_id")),
        table("Region", key()),
        relationships=[
            rel("Invoices", "dept_id", "Department"),
            rel("Department", "region_id", "Region"),
        ],
    )


def test_shortest_path_crosses_intermediate_tables() -> None:
    path = join_path(chain(), "Invoices", "Region")
    assert [r.to.table for r in path] == ["Department", "Region"]
    back = join_path(chain(), "Region", "Invoices")
    assert [step.from_.table for step in back] == ["Department", "Invoices"]
    assert join_path(chain(), "Department", "Department") == []
    assert find_cycle(chain()) is None


def test_inactive_relationship_is_not_a_path() -> None:
    model = definition(
        table("Invoices", key(), col("dept_id")),
        table("Department", key()),
        relationships=[rel("Invoices", "dept_id", "Department", active=False)],
    )
    with pytest.raises(ModelSchemaError, match="no relationship path"):
        join_path(model, "Invoices", "Department")


def test_ambiguous_path_is_reported_and_is_not_a_directed_cycle() -> None:
    model = definition(
        table("Invoices", key(), col("a_id"), col("b_id")),
        table("Channel", key(), col("region_id")),
        table("Owner", key(), col("region_id")),
        table("Region", key()),
        relationships=[
            rel("Invoices", "a_id", "Channel"),
            rel("Invoices", "b_id", "Owner"),
            rel("Channel", "region_id", "Region"),
            rel("Owner", "region_id", "Region"),
        ],
    )
    assert find_cycle(model) is None
    with pytest.raises(ModelSchemaError, match="ambiguous"):
        join_path(model, "Invoices", "Region")


def test_directed_cycle_is_reported() -> None:
    model = definition(
        table("A", key(), col("b_id")),
        table("B", key(), col("c_id")),
        table("C", key(), col("a_id")),
        relationships=[
            rel("A", "b_id", "B"),
            rel("B", "c_id", "C"),
            rel("C", "a_id", "A"),
        ],
    )
    assert find_cycle(model) == ["A", "B", "C", "A"]
    with pytest.raises(ModelSchemaError, match="cycle"):
        join_path(model, "A", "C")


def test_missing_table() -> None:
    with pytest.raises(ModelSchemaError, match="does not exist"):
        join_path(chain(), "Invoices", "Nope")
