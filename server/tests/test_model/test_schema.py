from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from magbi.connectors.types import DataType
from magbi.model.schema import (
    CalculatedColumnDef,
    ColumnDef,
    DatasetDefinition,
    DateTableConfig,
    HierarchyDef,
    HierarchyLevel,
    MeasureDef,
    RelationshipDef,
    RlsRoleDef,
    RlsTableFilter,
    SqlTableSource,
    TableDef,
)


def col(name: str, data_type: DataType = DataType.INTEGER, **kw: object) -> ColumnDef:
    return ColumnDef(name=name, data_type=data_type, **kw)  # type: ignore[arg-type]


def key(name: str = "id") -> ColumnDef:
    return col(name, is_primary_key=True, is_nullable=False)


def table(name: str, *columns: ColumnDef, **kw: object) -> TableDef:
    return TableDef(name=name, columns=list(columns), **kw)  # type: ignore[arg-type]


def link(from_table: str, to_table: str, **kw: object) -> RelationshipDef:
    return RelationshipDef.model_validate(
        {
            "from": {"table": from_table, "column": "dept_id"},
            "to": {"table": to_table, "column": "id"},
            "cardinality": "many-to-one",
            **kw,
        }
    )


def definition(*tables: TableDef, **kw: object) -> DatasetDefinition:
    return DatasetDefinition(tables=list(tables), **kw)  # type: ignore[arg-type]


def invoices_model() -> DatasetDefinition:
    invoices = table(
        "Invoices",
        key(),
        col("dept_id"),
        col("amount", DataType.DECIMAL),
        col("issued", DataType.DATE),
        measures=[MeasureDef(name="Total", expression="SUM(Invoices[amount])")],
        source=SqlTableSource(schema="dbo", table="Invoices"),
    )
    department = table(
        "Department",
        key(),
        col("name", DataType.STRING),
        source=SqlTableSource(schema="dbo", table="Department"),
    )
    return DatasetDefinition(
        connection_id=uuid.uuid4(),
        tables=[invoices, department],
        relationships=[link("Invoices", "Department")],
    )


def test_round_trip_keeps_the_from_side_and_the_source_schema() -> None:
    original = invoices_model()
    payload = original.model_dump(mode="json", by_alias=True)
    assert payload["schema_version"] == "1.0"
    assert payload["relationships"][0]["from"]["table"] == "Invoices"
    assert payload["tables"][0]["source"] == {
        "type": "table",
        "schema": "dbo",
        "table": "Invoices",
        "database": None,
    }
    restored = DatasetDefinition.model_validate(payload)
    assert restored == original
    assert restored.measure("total") is not None  # lookup is case-insensitive
    assert restored.table("Invoices").primary_key().name == "id"  # type: ignore[union-attr]


def test_names_are_trimmed() -> None:
    model = definition(table("  Invoices  ", key()))
    assert model.tables[0].name == "Invoices"


@pytest.mark.parametrize(
    "build",
    [
        lambda: definition(table("T", key()), table("T", key())),
        lambda: table("T", key("id"), key("id2")),
        lambda: table("T", col("a"), col("a")),
        lambda: table(
            "T",
            key(),
            measures=[
                MeasureDef(name="A", expression="1"),
                MeasureDef(name="a", expression="2"),
            ],
        ),
        lambda: definition(
            table("T", key(), measures=[MeasureDef(name="A", expression="1")]),
            table("U", key(), measures=[MeasureDef(name="a", expression="2")]),
        ),
        lambda: table(
            "T",
            key(),
            calculated_columns=[
                CalculatedColumnDef(
                    name="id", expression="1", data_type=DataType.INTEGER
                )
            ],
        ),
        lambda: MeasureDef(name="A[B]", expression="1"),
        lambda: MeasureDef(name="A", expression="   "),
        lambda: table("T", col("a", sort_by_column="missing")),
        lambda: table("T", key(), is_date_table=True),
        lambda: table("T", key(), is_date_table=True, date_column="id"),
        lambda: table("T", key(), date_column="id"),
        lambda: definition(
            table("T", key("id"), col("dept_id")), relationships=[link("T", "Missing")]
        ),
        lambda: definition(
            table("T", key(), col("dept_id")),
            table("U", col("id"), col("name", DataType.STRING)),
            relationships=[link("T", "U")],
        ),
        lambda: definition(
            table("T", key(), col("dept_id")), relationships=[link("T", "T")]
        ),
        lambda: RelationshipDef.model_validate(
            {
                "from": {"table": "A", "column": "id"},
                "to": {"table": "B", "column": "id"},
                "cardinality": "many-to-many",
            }
        ),
        lambda: RelationshipDef.model_validate(
            {
                "from": {"table": "A", "column": "id"},
                "to": {"table": "B", "column": "id"},
                "cardinality": "many-to-one",
                "cross_filter_direction": "both",
            }
        ),
    ],
)
def test_invalid_documents_are_rejected(build: object) -> None:
    with pytest.raises((ValidationError, ValueError)):
        build()  # type: ignore[operator]


def test_two_active_relationships_between_the_same_tables_are_rejected() -> None:
    invoices = table("Invoices", key(), col("ordered"), col("shipped"))
    dates = table(
        "Dates",
        col("day", DataType.DATE, is_primary_key=True),
        is_date_table=True,
        date_column="day",
    )
    with pytest.raises(ValidationError, match="more than one active"):
        DatasetDefinition(
            tables=[invoices, dates],
            relationships=[
                RelationshipDef.model_validate(
                    {
                        "from": {"table": "Invoices", "column": "ordered"},
                        "to": {"table": "Dates", "column": "day"},
                        "cardinality": "many-to-one",
                    }
                ),
                RelationshipDef.model_validate(
                    {
                        "from": {"table": "Invoices", "column": "shipped"},
                        "to": {"table": "Dates", "column": "day"},
                        "cardinality": "many-to-one",
                    }
                ),
            ],
        )


def test_a_second_relationship_is_allowed_when_inactive() -> None:
    invoices = table("Invoices", key(), col("ordered"), col("shipped"))
    dates = table(
        "Dates",
        col("day", DataType.DATE, is_primary_key=True),
        is_date_table=True,
        date_column="day",
    )
    model = DatasetDefinition(
        tables=[invoices, dates],
        relationships=[
            RelationshipDef.model_validate(
                {
                    "from": {"table": "Invoices", "column": "ordered"},
                    "to": {"table": "Dates", "column": "day"},
                    "cardinality": "many-to-one",
                }
            ),
            RelationshipDef.model_validate(
                {
                    "from": {"table": "Invoices", "column": "shipped"},
                    "to": {"table": "Dates", "column": "day"},
                    "cardinality": "many-to-one",
                    "is_active": False,
                }
            ),
        ],
    )
    assert len(model.relationships_of("Invoices", active_only=True)) == 1


def test_one_to_one_requires_a_key_on_both_sides() -> None:
    with pytest.raises(ValidationError, match="one-to-one"):
        DatasetDefinition(
            tables=[table("A", key(), col("b_id")), table("B", key())],
            relationships=[
                RelationshipDef.model_validate(
                    {
                        "from": {"table": "A", "column": "b_id"},
                        "to": {"table": "B", "column": "id"},
                        "cardinality": "one-to-one",
                    }
                )
            ],
        )


def test_role_must_filter_a_real_table() -> None:
    with pytest.raises(ValidationError, match="does not exist"):
        definition(
            table("T", key()),
            roles=[
                RlsRoleDef(
                    name="Dept",
                    table_filters=[
                        RlsTableFilter(table="Missing", expression="TRUE()")
                    ],
                )
            ],
        )


def test_hierarchy_level_must_name_a_column() -> None:
    with pytest.raises(ValidationError, match="does not exist"):
        table(
            "T",
            key(),
            hierarchies=[
                HierarchyDef(
                    name="H", levels=[HierarchyLevel(name="Year", column="Year")]
                )
            ],
        )


def test_date_table_config_bounds() -> None:
    assert DateTableConfig().fiscal_year_start_month == 1
    with pytest.raises(ValidationError):
        DateTableConfig(fiscal_year_start_month=13)
    with pytest.raises(ValidationError):
        DateTableConfig(first_day_of_week=7)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        DatasetDefinition.model_validate({"tables": [], "surprise": 1})


def test_query_and_csv_sources_round_trip() -> None:
    model = definition(
        table("Q", key(), source={"type": "query", "sql": "SELECT 1 AS id"}),  # type: ignore[arg-type]
        table("C", key(), source={"type": "csv", "file_path": "data.csv"}),  # type: ignore[arg-type]
    )
    restored = DatasetDefinition.model_validate(
        model.model_dump(mode="json", by_alias=True)
    )
    assert (
        restored.tables[0].source is not None
        and restored.tables[0].source.type == "query"
    )
    assert (
        restored.tables[1].source is not None
        and restored.tables[1].source.type == "csv"
    )
