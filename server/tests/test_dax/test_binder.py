from __future__ import annotations

import pytest

from magbi.connectors.types import DataType
from magbi.dax.binder import bind
from magbi.dax.errors import DaxError
from magbi.dax.parser import Binary, Call, ColumnRef, NameRef, TableRef, VarBlock
from magbi.model.schema import (
    ColumnDef,
    DatasetDefinition,
    MeasureDef,
    TableDef,
)


def column(name: str, data_type: DataType = DataType.INTEGER) -> ColumnDef:
    return ColumnDef(name=name, data_type=data_type)


def model() -> DatasetDefinition:
    return DatasetDefinition(
        tables=[
            TableDef(
                name="Sales",
                columns=[
                    column("Amount", DataType.DECIMAL),
                    column("Status", DataType.STRING),
                ],
                measures=[
                    MeasureDef(name="Total", expression="SUM(Sales[Amount])"),
                    MeasureDef(name="Again", expression="[Total] + 1"),
                    MeasureDef(name="LoopA", expression="[LoopB]"),
                    MeasureDef(name="LoopB", expression="[LoopA]"),
                ],
            ),
            TableDef(name="sales", columns=[column("id")]),
        ]
    )


def test_an_exact_table_name_wins() -> None:
    tree = bind(model(), "SUM(sales[id])")
    assert tree == Call("SUM", (ColumnRef("sales", "id", 1, 5),), 1, 1)


def test_a_unique_fold_matches_and_a_measure_expands() -> None:
    only = DatasetDefinition(
        tables=[
            TableDef(
                name="Sales",
                columns=[column("Amount", DataType.DECIMAL)],
                measures=[
                    MeasureDef(name="Total", expression="SUM(Sales[Amount])"),
                    MeasureDef(name="Again", expression="[total] + 1"),
                ],
            )
        ]
    )
    tree = bind(only, "[Again]")
    assert isinstance(tree, Binary) and tree.op == "+"
    assert isinstance(tree.left, Call) and tree.left.name == "SUM"
    folded = bind(only, "SUM(sales[amount])")
    assert isinstance(folded, Call)
    assert folded.args[0] == ColumnRef("Sales", "Amount", 1, 5)


def test_a_table_name_becomes_a_table_reference() -> None:
    only = DatasetDefinition(
        tables=[TableDef(name="Sales", columns=[column("Amount", DataType.DECIMAL)])]
    )
    assert bind(only, "COUNTROWS(Sales)") == Call(
        "COUNTROWS", (TableRef("Sales", 1, 11),), 1, 1
    )


def test_a_variable_hides_a_table_of_the_same_name() -> None:
    only = DatasetDefinition(
        tables=[TableDef(name="Sales", columns=[column("Amount")])]
    )
    tree = bind(only, "VAR Sales = 1 RETURN Sales")
    assert isinstance(tree, VarBlock) and isinstance(tree.body, NameRef)
    assert tree.body.name == "Sales"


def test_missing_names_and_cycles() -> None:
    source = model()
    with pytest.raises(DaxError, match="does not exist"):
        bind(source, "SUM(Sales[Missing])")
    with pytest.raises(DaxError, match="does not exist"):
        bind(source, "[Nope]")
    with pytest.raises(DaxError, match="ambiguous"):
        bind(source, "SUM(SALES[id])")
    with pytest.raises(DaxError, match="circular reference") as caught:
        bind(source, "[LoopA]")
    assert "[LoopA] -> [LoopB] -> [LoopA]" in caught.value.message
