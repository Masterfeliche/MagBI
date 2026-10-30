"""Filters flow from a dimension down to its facts, never across to another fact."""

from __future__ import annotations

from typing import Any

import duckdb

from magbi.connectors.types import DataType
from magbi.engine.executor import run_query
from magbi.engine.semantic import parse_query
from magbi.model.schema import MeasureDef, RelationshipDef
from tests.test_model.test_schema import col, definition, table


def _rel(fact: str, column: str, dim: str) -> RelationshipDef:
    return RelationshipDef.model_validate(
        {
            "from": {"table": fact, "column": column},
            "to": {"table": dim, "column": column},
            "cardinality": "many-to-one",
        }
    )


def _star() -> tuple[Any, Any]:
    model = definition(
        table("Warehouse", col("Warehouse", DataType.STRING, is_primary_key=True)),
        table(
            "Batch",
            col("BatchID", DataType.STRING),
            col("Item", DataType.STRING),
            col("Warehouse", DataType.STRING),
            measures=[MeasureDef(name="Batches", expression="DISTINCTCOUNT(Batch[BatchID])")],
        ),
        table(
            "CountLine",
            col("Count", DataType.STRING),
            col("Warehouse", DataType.STRING),
            measures=[MeasureDef(name="Lines", expression="COUNTROWS(CountLine)")],
        ),
        relationships=[_rel("Batch", "Warehouse", "Warehouse"), _rel("CountLine", "Warehouse", "Warehouse")],
    )
    con = duckdb.connect()
    con.execute('CREATE TABLE "Warehouse" ("Warehouse" VARCHAR)')
    con.execute("INSERT INTO \"Warehouse\" VALUES ('CW2'), ('CW3')")
    con.execute('CREATE TABLE "Batch" ("BatchID" VARCHAR, "Item" VARCHAR, "Warehouse" VARCHAR)')
    con.execute(
        "INSERT INTO \"Batch\" VALUES ('b1', 'Amoxicillin', 'CW2'), ('b2', 'Pethidine', 'CW3'), "
        "('b3', 'Catgut', 'CW2')"
    )
    con.execute('CREATE TABLE "CountLine" ("Count" VARCHAR, "Warehouse" VARCHAR)')
    con.execute("INSERT INTO \"CountLine\" VALUES ('Oct count', 'CW2'), ('Oct count', 'CW2'), ('Smoke', 'CW3')")
    return model, con


def _where(table_name: str, column: str, value: str) -> dict[str, Any]:
    return {"column": {"table": table_name, "column": column}, "operator": "eq", "values": [value]}


def test_a_dimension_filter_reaches_every_fact_under_it() -> None:
    model, con = _star()
    query = parse_query(
        {
            "select": [
                {"measure": {"table": "Batch", "measure": "Batches"}},
                {"measure": {"table": "CountLine", "measure": "Lines"}},
            ],
            "where": [_where("Warehouse", "Warehouse", "CW2")],
        }
    )
    result = run_query(model, query, con)
    assert result["rows"] == [[2, 2]]
    assert "ignoredFilters" not in result


def test_a_filter_on_one_fact_does_not_leak_into_another_fact() -> None:
    model, con = _star()
    query = parse_query(
        {
            "select": [{"measure": {"table": "Batch", "measure": "Batches"}}],
            "where": [_where("CountLine", "Count", "Smoke")],
        }
    )
    result = run_query(model, query, con)
    assert result["rows"] == [[3]]
    assert result["ignoredFilters"] == ["CountLine[Count]"]


def test_detail_rows_with_no_measure_are_filtered_too() -> None:
    model, con = _star()
    query = parse_query(
        {
            "select": [{"column": {"table": "Batch", "column": "Item"}}],
            "where": [_where("Warehouse", "Warehouse", "CW3")],
        }
    )
    result = run_query(model, query, con)
    assert result["rows"] == [["Pethidine"]]


def test_a_filter_that_reaches_one_of_two_facts_is_not_reported() -> None:
    model, con = _star()
    query = parse_query(
        {
            "select": [
                {"measure": {"table": "Batch", "measure": "Batches"}},
                {"measure": {"table": "CountLine", "measure": "Lines"}},
            ],
            "where": [_where("CountLine", "Count", "Oct count")],
        }
    )
    result = run_query(model, query, con)
    assert result["rows"] == [[3, 2]]
    assert "ignoredFilters" not in result
