from __future__ import annotations

import pytest

from magbi.connectors.types import DataType
from magbi.dax.binder import bind_calculated_column, bind_measure
from magbi.dax.errors import DaxError
from magbi.dax.parser import Call
from magbi.model.schema import ColumnDef, DatasetDefinition, MeasureDef, TableDef


def _model() -> DatasetDefinition:
    return DatasetDefinition(
        tables=[
            TableDef(
                name="Sales",
                columns=[
                    ColumnDef(name="Amount", data_type=DataType.DECIMAL),
                    ColumnDef(name="Status", data_type=DataType.STRING),
                    ColumnDef(name="Placed", data_type=DataType.DATE),
                    ColumnDef(name="Flag", data_type=DataType.BOOLEAN),
                ],
                measures=[
                    MeasureDef(name="Total", expression="SUM(Sales[Amount])"),
                ],
            )
        ]
    )


def test_numeric_aggregates_and_min_max() -> None:
    model = _model()
    total = bind_measure(model, "SUM(Sales[Amount])")
    assert isinstance(total, Call) and total.name == "SUM"
    bind_measure(model, "MIN(Sales[Status])")
    bind_measure(model, "MAX(Sales[Placed])")
    bind_measure(model, "COUNT(Sales[Status])")
    bind_measure(model, "COUNTA(Sales[Status])")
    bind_measure(model, "DISTINCTCOUNT(Sales[Status])")
    bind_measure(model, "[Total]")
    with pytest.raises(DaxError, match="numeric column"):
        bind_measure(model, "SUM(Sales[Status])")
    with pytest.raises(DaxError, match="number, date, or string"):
        bind_measure(model, "MIN(Sales[Flag])")
    with pytest.raises(DaxError, match="expects a table"):
        bind_measure(model, "COUNTROWS(Sales[Amount])")


def test_measures_aggregate_and_calculated_columns_do_not() -> None:
    model = _model()
    with pytest.raises(DaxError, match="measures must aggregate"):
        bind_measure(model, "Sales[Amount] + 1")
    assert bind_calculated_column(model, "Sales[Amount] + 1")
    with pytest.raises(DaxError, match="cannot contain aggregations"):
        bind_calculated_column(model, "SUM(Sales[Amount])")
