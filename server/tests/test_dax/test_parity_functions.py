"""The DAX functions added for Power BI parity, each checked through the engine on DuckDB.

Expected figures are worked out by hand from the rows below.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import duckdb
import pytest

from magbi.connectors.types import DataType
from magbi.dax.binder import bind_measure
from magbi.dax.errors import DaxError
from magbi.engine.errors import QueryError
from magbi.engine.executor import run_query
from magbi.engine.semantic import parse_query
from magbi.model.schema import (
    ColumnDef,
    DatasetDefinition,
    MeasureDef,
    RelationshipDef,
    TableDef,
)

# OrderID, OrderDate, Region, Product, Qty
SALES = [
    (1, dt.date(2025, 11, 20), "North", "Gloves", 2),
    (2, dt.date(2026, 1, 10), "North", "Masks", 5),
    (3, dt.date(2026, 2, 3), "South", "Gloves", 1),
    (4, dt.date(2026, 2, 27), "South", "Masks", 4),
    (5, dt.date(2026, 3, 15), "East", "Gloves", 3),
    (6, dt.date(2026, 4, 2), "North", "Gloves", 1),
]
PRICES = {"Gloves": 10.0, "Masks": 2.5}
# Revenue per row: 20, 12.5, 10, 10, 30, 10 → 92.5; North 42.5, South 20, East 30.


def _rel(source: str, column: str, target: str, target_column: str | None = None) -> RelationshipDef:
    return RelationshipDef.model_validate(
        {"from": {"table": source, "column": column}, "to": {"table": target, "column": target_column or column}, "cardinality": "many-to-one"}
    )


def _model(*measures: tuple[str, str]) -> DatasetDefinition:
    return DatasetDefinition(
        tables=[
            TableDef(
                name="Sales",
                columns=[
                    ColumnDef(name="OrderID", data_type=DataType.INTEGER),
                    ColumnDef(name="OrderDate", data_type=DataType.DATE),
                    ColumnDef(name="Region", data_type=DataType.STRING),
                    ColumnDef(name="Product", data_type=DataType.STRING),
                    ColumnDef(name="Qty", data_type=DataType.INTEGER),
                ],
                measures=[MeasureDef(name="Qty total", expression="SUM(Sales[Qty])")]
                + [MeasureDef(name=name, expression=source) for name, source in measures],
            ),
            TableDef(
                name="Product",
                columns=[
                    ColumnDef(name="Product", data_type=DataType.STRING, is_primary_key=True, is_nullable=False),
                    ColumnDef(name="UnitPrice", data_type=DataType.DECIMAL),
                ],
            ),
            TableDef(
                name="Region",
                columns=[ColumnDef(name="Region", data_type=DataType.STRING, is_primary_key=True, is_nullable=False)],
            ),
            TableDef(
                name="Date",
                is_date_table=True,
                date_column="Date",
                columns=[ColumnDef(name="Date", data_type=DataType.DATE, is_primary_key=True, is_nullable=False)],
            ),
        ],
        relationships=[
            _rel("Sales", "Product", "Product"),
            _rel("Sales", "Region", "Region"),
            _rel("Sales", "OrderDate", "Date", "Date"),
        ],
    )


@pytest.fixture(scope="module")
def con() -> Any:
    db = duckdb.connect()
    db.execute('CREATE TABLE "Sales" ("OrderID" INTEGER, "OrderDate" DATE, "Region" VARCHAR, "Product" VARCHAR, "Qty" INTEGER)')
    db.executemany('INSERT INTO "Sales" VALUES (?, ?, ?, ?, ?)', SALES)
    db.execute('CREATE TABLE "Product" ("Product" VARCHAR, "UnitPrice" DOUBLE)')
    db.executemany('INSERT INTO "Product" VALUES (?, ?)', list(PRICES.items()))
    db.execute('CREATE TABLE "Region" ("Region" VARCHAR)')
    db.executemany('INSERT INTO "Region" VALUES (?)', [("North",), ("South",), ("East",), ("West",)])
    db.execute(
        "CREATE TABLE \"Date\" AS SELECT CAST(d AS DATE) AS \"Date\" "
        "FROM range(DATE '2025-01-01', DATE '2026-12-31', INTERVAL 1 DAY) t(d)"
    )
    return db


def _ask(con: Any, source: str, *, by: str | None = None, where: list[dict[str, Any]] | None = None) -> list[list[Any]]:
    model = _model(("M", source))
    select: list[dict[str, Any]] = [{"measure": {"table": "Sales", "measure": "M"}}]
    if by:
        table, column = by.split(".")
        select.insert(0, {"column": {"table": table, "column": column}})
    query = parse_query({"select": select, **({"where": where} if where else {}), **({"orderBy": [{"select": 0}]} if by else {})})
    return run_query(model, query, con)["rows"]  # type: ignore[return-value]


def _one(con: Any, source: str, **kw: Any) -> Any:
    return _ask(con, source, **kw)[0][0]


def _dates(start: str, end: str) -> list[dict[str, Any]]:
    column = {"table": "Date", "column": "Date"}
    return [{"column": column, "operator": "gte", "values": [start]}, {"column": column, "operator": "lte", "values": [end]}]


# ---------------------------------------------------------------- iterators and RELATED


def test_sumx_with_related_matches_row_by_row_revenue(con: Any) -> None:
    revenue = "SUMX(Sales, Sales[Qty] * RELATED(Product[UnitPrice]))"
    assert _one(con, revenue) == pytest.approx(92.5)
    # West has no sales, so like Power BI the visual has no West row.
    assert {row[0]: row[1] for row in _ask(con, revenue, by="Region.Region")} == {
        "East": pytest.approx(30), "North": pytest.approx(42.5), "South": pytest.approx(20)
    }


def test_the_other_iterators_and_a_filtered_table(con: Any) -> None:
    assert _one(con, "AVERAGEX(Sales, Sales[Qty] * 2)") == pytest.approx(16 / 6 * 2)
    assert _one(con, "MINX(Sales, Sales[Qty] - 1)") == 0
    assert _one(con, "MAXX(Sales, Sales[Qty] * RELATED(Product[UnitPrice]))") == pytest.approx(30)
    assert _one(con, "COUNTX(Sales, Sales[OrderID])") == 6
    assert _one(con, "SUMX(FILTER(Sales, Sales[Qty] > 2), Sales[Qty])") == 12


def test_row_expressions_are_checked(con: Any) -> None:
    model = _model()
    with pytest.raises(DaxError, match="RELATED"):
        bind_measure(model, "SUMX(Sales, Sales[Qty] * Product[UnitPrice])")
    with pytest.raises(DaxError, match="not measures or aggregations"):
        bind_measure(model, "SUMX(Sales, [Qty total])")
    with pytest.raises(DaxError, match="works only in the row expression"):
        bind_measure(model, "SUM(Sales[Qty]) + RELATED(Product[UnitPrice])")


# ---------------------------------------------------------------- logic and context


def test_switch_iferror_and_coalesce(con: Any) -> None:
    by = {row[0]: row[1] for row in _ask(con, 'SWITCH(SELECTEDVALUE(Region[Region]), "North", 1, "South", 2, 0) + SUM(Sales[Qty]) * 0', by="Region.Region")}
    assert by["North"] == 1 and by["South"] == 2 and by["East"] == 0
    assert _one(con, 'SWITCH(TRUE(), SUM(Sales[Qty]) > 100, "big", SUM(Sales[Qty]) > 10, "medium", "small")') == "medium"
    assert _one(con, "IFERROR(SUM(Sales[Qty]) / 0, -1)") == -1
    assert _one(con, "COALESCE(SUM(Sales[Qty]) * BLANK(), 7)") == 7


def test_selectedvalue_hasonevalue_and_isfiltered(con: Any) -> None:
    by = {row[0]: row[1] for row in _ask(con, 'SELECTEDVALUE(Sales[Region], "several")', by="Region.Region")}
    assert by["North"] == "North"
    assert _one(con, 'SELECTEDVALUE(Sales[Region], "several")') == "several"
    assert _one(con, "HASONEVALUE(Sales[Region])") is False
    north = [{"column": {"table": "Region", "column": "Region"}, "operator": "eq", "values": ["North"]}]
    assert _one(con, "HASONEVALUE(Sales[Region])", where=north) is True
    assert _one(con, "IF(ISFILTERED(Region[Region]), SUM(Sales[Qty]), -1)", where=north) == 8
    assert _one(con, "IF(ISFILTERED(Region[Region]), SUM(Sales[Qty]), -1)") == -1


# ---------------------------------------------------------------- text, maths, dates


def test_text_functions(con: Any) -> None:
    north = [{"column": {"table": "Region", "column": "Region"}, "operator": "eq", "values": ["North"]}]
    assert _one(con, 'UPPER(SELECTEDVALUE(Sales[Region])) & "-" & LOWER(SELECTEDVALUE(Sales[Region]))', where=north) == "NORTH-north"
    assert _one(con, "LEFT(SELECTEDVALUE(Sales[Region]), 2) & RIGHT(SELECTEDVALUE(Sales[Region]), 2) & MID(SELECTEDVALUE(Sales[Region]), 2, 3)", where=north) == "Nothort"
    assert _one(con, "LEN(SELECTEDVALUE(Sales[Region])) + 0 * SUM(Sales[Qty])", where=north) == 5
    assert _one(con, 'CONCATENATE("Qty ", FORMAT(SUM(Sales[Qty]) * 1000, "#,0"))') == "Qty 16,000"
    assert _one(con, 'FORMAT(SUM(Sales[Qty]) / 3, "0.0")') == "5.3"
    assert _one(con, 'FORMAT(DIVIDE(SUM(Sales[Qty]), 64), "0.0%")') == "25.0%"
    assert _one(con, 'FORMAT(MAX(Sales[OrderDate]), "dd mmm yyyy")') == "02 Apr 2026"
    assert _one(con, 'FORMAT(MIN(Sales[OrderDate]), "mmm yy")') == "Nov 25"
    with pytest.raises(QueryError, match="FORMAT supports"):
        _one(con, 'FORMAT(SUM(Sales[Qty]), "$ ##")')


def test_maths_functions(con: Any) -> None:
    assert _one(con, "ROUND(SUM(Sales[Qty]) / 3, 1)") == pytest.approx(5.3)
    assert _one(con, "ROUND(SUM(Sales[Qty]) / 6.4, 0)") == 3  # 2.5 rounds away from zero
    assert _one(con, "ABS(0 - SUM(Sales[Qty]))") == 16
    assert _one(con, "INT(SUM(Sales[Qty]) / 3)") == 5
    assert _one(con, "MOD(0 - SUM(Sales[Qty]), 3)") == 2  # DAX: the sign of the divisor
    assert _one(con, "POWER(SUM(Sales[Qty]), 2)") == 256


def test_date_functions(con: Any) -> None:
    assert _one(con, "YEAR(MAX(Sales[OrderDate])) * 100 + MONTH(MAX(Sales[OrderDate]))") == 202604
    assert _one(con, "DAY(MIN(Sales[OrderDate]))") == 20
    assert _one(con, "DATEDIFF(MIN(Sales[OrderDate]), MAX(Sales[OrderDate]), MONTH)") == 5
    assert _one(con, "DATEDIFF(MIN(Sales[OrderDate]), MAX(Sales[OrderDate]), DAY)") == 133
    assert _one(con, "EOMONTH(MAX(Sales[OrderDate]), 1)") == "2026-05-31"  # dates come back as ISO text
    assert _one(con, "WEEKDAY(MAX(Sales[OrderDate]))") == 5  # Thu 2 Apr 2026, Sunday = 1
    assert _one(con, "WEEKDAY(MAX(Sales[OrderDate]), 2)") == 4
    assert _one(con, "WEEKDAY(MAX(Sales[OrderDate]), 3)") == 3
    assert _one(con, "YEAR(DATE(2026, 2, 28)) * 10000 + MONTH(DATE(2026, 2, 28)) * 100 + DAY(DATE(2026, 2, 28)) + 0 * SUM(Sales[Qty])") == 20260228
    assert _one(con, "DATEDIFF(DATE(2026, 1, 1), TODAY(), DAY) + 0 * SUM(Sales[Qty])") >= 0


# ---------------------------------------------------------------- time intelligence


def test_quarter_and_month_to_date(con: Any) -> None:
    march = _dates("2026-03-01", "2026-03-31")
    assert _one(con, "TOTALQTD(SUM(Sales[Qty]), Date[Date])", where=march) == 13  # Jan 5 + Feb 1 + Feb 4 + Mar 3
    assert _one(con, "TOTALMTD(SUM(Sales[Qty]), Date[Date])", where=march) == 3
    # TOTALYTD failed in every visual before: the engine compiled it once with no date filter.
    assert _one(con, "TOTALYTD(SUM(Sales[Qty]), Date[Date])", where=march) == 13
    assert _one(con, "CALCULATE(SUM(Sales[Qty]), DATESYTD(Date[Date]))", where=march) == 13


def test_previous_and_parallel_periods(con: Any) -> None:
    march = _dates("2026-03-01", "2026-03-31")
    assert _one(con, "CALCULATE(SUM(Sales[Qty]), PREVIOUSMONTH(Date[Date]))", where=march) == 5  # February
    assert _one(con, "CALCULATE(SUM(Sales[Qty]), PREVIOUSYEAR(Date[Date]))", where=march) == 2  # 2025
    assert _one(con, "CALCULATE(SUM(Sales[Qty]), PARALLELPERIOD(Date[Date], -1, QUARTER))", where=_dates("2026-04-01", "2026-04-30")) == 13
    assert _one(con, "CALCULATE(SUM(Sales[Qty]), PARALLELPERIOD(Date[Date], -2, MONTH))", where=march) == 5  # January
    with pytest.raises(QueryError, match="needs a date filter"):
        _one(con, "CALCULATE(SUM(Sales[Qty]), PREVIOUSMONTH(Date[Date]))")


# ---------------------------------------------------------------- ranking


def test_rankx_over_the_visual_rows(con: Any) -> None:
    ranks = {row[0]: row[1] for row in _ask(con, "RANKX(ALL(Region), SUM(Sales[Qty]))", by="Region.Region")}
    # North 8, South 5, East 3, West nothing
    assert ranks["North"] == 1 and ranks["South"] == 2 and ranks["East"] == 3
    ascending = {row[0]: row[1] for row in _ask(con, "RANKX(ALL(Region), SUM(Sales[Qty]), , ASC)", by="Region.Region")}
    assert ascending["East"] == 1 and ascending["North"] == 3
    model = _model(("Total", "SUM(Sales[Qty])"))
    with pytest.raises(DaxError, match="ranks by a measure or an aggregation"):
        bind_measure(model, "RANKX(ALL(Region), Sales[Qty])")


def test_unsupported_functions_say_what_to_use(con: Any) -> None:
    with pytest.raises(DaxError, match="Top N filter"):
        bind_measure(_model(), "CALCULATE(SUM(Sales[Qty]), TOPN(3, Sales, Sales[Qty]))")
