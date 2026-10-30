"""The shared Warehouse model: dimensions, relationships, measures."""

from __future__ import annotations

from typing import Any

from scripts.wms.msd_extract import DIMENSIONS

BATCH = "DISTINCTCOUNT(Batch[BatchID])"

MEASURES: dict[str, list[tuple[str, str, str | None]]] = {
    "Batch": [
        ("Batches", BATCH, "#,0"),
        ("Expiring 90", f"CALCULATE({BATCH}, Batch[WindowOrder] = 1)", "#,0"),
        ("Expired", f"CALCULATE({BATCH}, Batch[WindowOrder] = 0)", "#,0"),
        ("No expiry", f"CALCULATE({BATCH}, Batch[WindowOrder] = 6)", "#,0"),
        ("Expiring 90 share", "DIVIDE([Expiring 90], [Batches])", "0%"),
    ],
    "StockLine": [
        ("Stock lines", "COUNTROWS(StockLine)", "#,0"),
        ("SKUs", "DISTINCTCOUNT(StockLine[SKUID])", "#,0"),
    ],
    "FEFO": [("FEFO breaches", "COUNTROWS(FEFO)", "#,0")],
    "Chain": [
        ("Chain count", "SUM(Chain[Count])", "#,0"),
        ("Chain age", "MAX(Chain[AgeDays])", "#,0"),
        ("Chain flags", "SUM(Chain[Flags])", "#,0"),
    ],
    "CountLine": [
        ("Count lines", "COUNTROWS(CountLine)", "#,0"),
        ("Exact lines", 'CALCULATE(COUNTROWS(CountLine), CountLine[Result] = "Exact")', "#,0"),
        ("Variances", 'CALCULATE(COUNTROWS(CountLine), CountLine[Result] = "Variance")', "#,0"),
        ("Short lines", 'CALCULATE(COUNTROWS(CountLine), CountLine[VarianceNote] = "Short")', "#,0"),
        ("Over lines", 'CALCULATE(COUNTROWS(CountLine), CountLine[VarianceNote] = "Over")', "#,0"),
        ("Accuracy", "DIVIDE([Exact lines], [Count lines])", "0.0%"),
        ("Physical counts", "DISTINCTCOUNT(CountLine[CountNo])", "#,0"),
    ],
    "StockItem": [
        ("Stocked items", "COUNTROWS(StockItem)", "#,0"),
        ("Counted items", 'CALCULATE(COUNTROWS(StockItem), StockItem[Coverage] = "Counted")', "#,0"),
        ("Coverage", "DIVIDE([Counted items], [Stocked items])", "0.0%"),
    ],
    "Movement": [
        ("Movements", "COUNTROWS(Movement)", "#,0"),
        ("Receipts", 'CALCULATE(COUNTROWS(Movement), Movement[MovementGroup] = "Receipt")', "#,0"),
        ("Receipt share", "DIVIDE([Receipts], [Movements])", "0%"),
        ("Movement months", "DISTINCTCOUNT(Movement[MovementMonth])", "#,0"),
    ],
    "Adjustment": [("Adjustments", "COUNTROWS(Adjustment)", "#,0")],
    "Request": [
        ("Requests", "COUNTROWS(Request)", "#,0"),
        ("Open requests", 'CALCULATE(COUNTROWS(Request), Request[Status] = "Open")', "#,0"),
        ("Closed requests", 'CALCULATE(COUNTROWS(Request), Request[Status] = "Closed")', "#,0"),
        ("Cancelled requests", 'CALCULATE(COUNTROWS(Request), Request[Status] = "Cancelled")', "#,0"),
        ("Oldest open", 'CALCULATE(MIN(Request[Raised]), Request[Status] = "Open")', None),
    ],
    "Issue": [("Issues", "COUNTROWS(Issue)", "#,0")],
    "Transfer": [
        ("Transfers", "COUNTROWS(Transfer)", "#,0"),
        ("In transit", "SUM(Transfer[InTransit])", "#,0"),
        ("Late transfers", "SUM(Transfer[Late])", "#,0"),
    ],
    "Delivery": [
        ("Delivery notes", "COUNTROWS(Delivery)", "#,0"),
        ("Shipped", "SUM(Delivery[Shipped])", "#,0"),
        ("On time shipped", "CALCULATE(COUNTROWS(Delivery), Delivery[Shipped] = 1, Delivery[OnTime] = 1)", "#,0"),
        ("On time share", "DIVIDE([On time shipped], [Shipped])", "0.0%"),
    ],
}


def _relationship(fact: str, column: str, dim: str, dim_column: str) -> dict[str, Any]:
    return {
        "from": {"table": fact, "column": column},
        "to": {"table": dim, "column": dim_column},
        "cardinality": "many-to-one",
    }


def build_definition(current: dict[str, Any]) -> dict[str, Any]:
    """The uploaded tables plus relationships, measures and sort orders."""
    tables = {table["name"]: table for table in current["tables"]}
    relationships = []
    for dim, (column, facts) in DIMENSIONS.items():
        for fact in facts:
            relationships.append(_relationship(fact, column, dim, column))
    relationships.append(_relationship("Batch", "ExpiryMonth", "Month", "ExpiryMonth"))
    for table_name, measures in MEASURES.items():
        tables[table_name]["measures"] = [
            {"name": name, "expression": expression, **({"format": fmt} if fmt else {})}
            for name, expression, fmt in measures
        ]
    for dim, (column, _facts) in DIMENSIONS.items():
        for col in tables[dim]["columns"]:
            if col["name"] == column:
                col["is_primary_key"] = True
                col["is_nullable"] = False
    for col in tables["Month"]["columns"]:
        if col["name"] == "MonthLabel":
            col["sort_by_column"] = "ExpiryMonth"
        if col["name"] == "ExpiryMonth":
            col["is_primary_key"] = True
            col["is_nullable"] = False
    return {**current, "tables": list(tables.values()), "relationships": relationships}
