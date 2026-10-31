"""Build the Warehouse dataset and the W1, W4 and W7 dashboards in MagBI.

    MAGBI_MSD_ENV=<path to .env.db> python -m scripts.wms.build_wms --workspace <id>

Reads MSD_ERP read-only, uploads a snapshot, writes the model, then creates or
updates the three reports. Run the QA gate afterwards (scripts.qa_gate).
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from scripts.magbi_lib import (
    ACTION_IF_ANY,
    CHAIN_NOTES,
    NONE_IF_ZERO,
    WATCH_IF_ANY,
    Api,
    Page,
    c,
    higher_is_better,
    layout_a,
    layout_b,
    m,
    where,
)
from scripts.wms.msd_extract import DIMENSIONS, extract, table_name
from scripts.wms.queries import DIM_QUERIES, QUERIES
from scripts.wms.wms_model import build_definition

DATASET = "Warehouse (MSD_ERP)"
WINDOWS = ["≤ 90 d", "91–180 d", "181–365 d", "> 1 year"]
DAYS_LEFT = {"steps": [{"max": 30, "tone": "action"}, {"max": 90, "tone": "watch"}], "otherwise": "info", "blank": "none"}


def load_dataset(api: Api, wid: str, folder: Path) -> str:
    did = api.dataset(wid, DATASET)
    names = [table_name(key) for key in QUERIES] + list(DIMENSIONS)
    for name in names:
        api.upload(f"/workspaces/{wid}/datasets/{did}/upload", folder / f"{name}.csv", name)
    current = api.get(f"/workspaces/{wid}/datasets/{did}/definition")
    model = build_definition(current["definition"])
    api.put(f"/workspaces/{wid}/datasets/{did}/definition", {"model_version": current["model_version"], "definition": model})
    return did


def go_live(api: Api, wid: str, did: str, connection_id: str) -> dict[str, Any]:
    """Point every table at a read-only query on the connection and refresh from MSD_ERP."""
    current = api.get(f"/workspaces/{wid}/datasets/{did}/definition")
    model = current["definition"]
    sql = {table_name(key): text for key, text in QUERIES.items()} | DIM_QUERIES
    for table in model["tables"]:
        if table["name"] in sql:
            table["source"] = {"type": "query", "sql": sql[table["name"]].strip()}
    model["connection_id"] = connection_id
    api.put(f"/workspaces/{wid}/datasets/{did}/definition", {"model_version": current["model_version"], "definition": model})
    return dict(api.post(f"/workspaces/{wid}/datasets/{did}/refresh", {}))


# ---------------------------------------------------------------- W1


def w1_stock_expiry(did: str) -> dict[str, Any]:
    page = Page("w1")
    xs = layout_a(
        page,
        crumb="Warehouse / Stock and expiry",
        title="Stock & Expiry",
        question="What is on the shelf, and what expires before we can use it?",
        units="Batches · stock lines · days",
        filters=[(c("Warehouse", "Warehouse"), "Warehouse"), (c("Category", "Category"), "Category")],
        highlight=["Storage"],
        notes=CHAIN_NOTES,
    )
    y = 186
    page.kpi(xs[0], y, 328, "Batches on hand", m("Batch", "Batches"), rule=NONE_IF_ZERO,
             extra=[m("StockLine", "Stock lines"), m("StockLine", "SKUs")], status={"none": "No batches held"},
             context="{1} stock lines · {2} SKUs")
    page.kpi(xs[1], y, 328, "Expiring in 90 days", m("Batch", "Expiring 90"), rule=WATCH_IF_ANY,
             extra=[m("Batch", "Expiring 90 share"), m("Batch", "Batches")], extra_formats=["pct0"], no_data_if=2,
             status={"watch": "Watch · {1} of batches", "good": "None expiring soon"}, context="Expiry within 90 days of today")
    page.kpi(xs[2], y, 328, "Expired on the shelf", m("Batch", "Expired"), rule=ACTION_IF_ANY,
             extra=[m("Batch", "Batches")], no_data_if=1, status={"good": "None held"}, context="Checked against today's date")
    page.kpi(xs[3], y, 328, "Batches without expiry", m("Batch", "No expiry"), rule=WATCH_IF_ANY,
             extra=[m("Batch", "Batches")], no_data_if=1, status={"watch": "No date recorded", "good": "Every batch dated"},
             context="Of {1} batches")
    page.kpi(xs[4], y, 328, "FEFO breaches", m("FEFO", "FEFO breaches"), rule=ACTION_IF_ANY,
             status={"good": "Oldest batch issued first"}, context="Issues checked against expiry order")

    expiring = [where("Batch", "WindowOrder", "gte", 1), where("Batch", "WindowOrder", "lte", 4)]
    page.panel(
        "calendar", (28, 326, 1180, 300), "When stock expires", "batches on hand by expiry month · amber = next 90 days",
        {"x-axis": [c("Month", "MonthLabel")], "columns": [c("Month", "ExpiryMonth"), c("Month", "InNext90Days")], "y-axis": [m("Batch", "Batches")]},
        expiring, allMembers=True, flagTone="watch", labelEvery=3, tooltip="{0} batches expire in {1}",
    )
    page.panel(
        "donut", (1224, 326, 508, 300), "Batches by storage class", "batches on hand",
        {"x-axis": [c("Batch", "StorageClass")], "y-axis": [m("Batch", "Batches")]},
        unit="batches", header="Class", valueHeader="Batches",
    )
    page.panel(
        "pareto", (28, 642, 520, 324), "Expiring within a year · Pareto", "batches by category",
        {"x-axis": [c("Category", "Category")], "y-axis": [m("Batch", "Batches")]},
        [where("Batch", "WindowOrder", "gte", 1), where("Batch", "WindowOrder", "lte", 3)], seriesName="Batches",
    )
    page.panel(
        "heatmap", (564, 642, 560, 324), "Expiry window by category", "batches on hand",
        {"x-axis": [c("Category", "Category")], "legend": [c("Batch", "Window")], "y-axis": [m("Batch", "Batches")]},
        expiring, columnOrder=WINDOWS, actionColumn=WINDOWS[0], actionLabel="Within 90 days", rowHeader="Category",
    )
    page.panel(
        "grid", (1140, 642, 592, 324), "Expiring soonest", "move or issue first",
        {"columns": [c("Batch", "Item"), c("Batch", "ExpDate"), c("Batch", "DaysLeft"), c("Batch", "QtyOnHand")]},
        [where("Batch", "WindowOrder", "eq", 1)],
        orderBy=[{"select": 2, "direction": "asc"}, {"select": 0, "direction": "asc"}], limit=25,
        columns=[
            {"header": "Item"},
            {"header": "Expires", "format": "date"},
            {"header": "Days left", "align": "right", "pill": {"rule": DAYS_LEFT, "text": "{0} d"}},
            {"header": "Qty", "align": "right", "format": "whole"},
        ],
    )
    return page.report("Stock & Expiry", did)


# ---------------------------------------------------------------- W4


def w4_accuracy(did: str) -> dict[str, Any]:
    page = Page("w4")
    ys = layout_b(
        page,
        crumb="Warehouse / Accuracy",
        title="Stock Accuracy & Control",
        question="Does the system match the shelf, and what moved?",
        units="Count lines · movements · %",
        filters=[(c("Warehouse", "Warehouse"), "Warehouse"), (c("CountLine", "Count"), "Count")],
        highlight=["Storage"],
        notes=CHAIN_NOTES,
    )
    x, w = 40, 316
    accuracy = higher_is_better(0.98, 0.95)
    page.kpi(x, ys[0], w, "Count accuracy", m("CountLine", "Accuracy"), rule=accuracy, fmt="pct1",
             extra=[m("CountLine", "Exact lines"), m("CountLine", "Count lines")],
             status={"none": "No count lines yet"}, context="{1} of {2} count lines exact")
    page.kpi(x, ys[1], w, "Count variances", m("CountLine", "Variances"), rule=WATCH_IF_ANY,
             extra=[m("CountLine", "Short lines"), m("CountLine", "Over lines"), m("CountLine", "Count lines")], no_data_if=3,
             status={"good": "Every line exact", "watch": "To investigate"}, context="{1} short · {2} over")
    page.kpi(x, ys[2], w, "Count coverage", m("StockItem", "Coverage"), rule=higher_is_better(0.9, 0.0), fmt="pct1",
             extra=[m("StockItem", "Counted items"), m("StockItem", "Stocked items")],
             status={"watch": "Below 90% counted"}, context="{1} of {2} stocked items counted")
    page.kpi(x, ys[3], w, "Stock movements", m("Movement", "Movements"), rule=NONE_IF_ZERO,
             extra=[m("Movement", "Receipt share"), m("Movement", "Movement months")], extra_formats=["pct0", "whole"],
             context="{1} receipts · {2} month(s) recorded")
    page.kpi(x, ys[4], w, "Adjustments posted", m("Adjustment", "Adjustments"), rule=NONE_IF_ZERO,
             status={"none": "None yet"}, context="Adjustments posted after counts", context_zero="Variances not adjusted in the ERP")

    page.panel("meter", (384, 186, 320, 250), "Count accuracy", "count lines exact",
               {"y-axis": [m("CountLine", "Accuracy")]}, target=0.98, rule=accuracy, format="pct1",
               blankText="– No count lines yet")
    page.panel("stack100", (720, 186, 1012, 250), "Exact against variance, by warehouse", "% of count lines",
               {"x-axis": [c("Warehouse", "Warehouse")], "legend": [c("CountLine", "Result")], "y-axis": [m("CountLine", "Count lines")]},
               partOrder=["Exact", "Variance"], colours={"Exact": "good", "Variance": "action"})
    page.panel("bars", (384, 452, 860, 250), "Stock movements by type", "movements recorded",
               {"x-axis": [c("Movement", "MovementGroup")], "y-axis": [m("Movement", "Movements")]}, unit="movements")
    page.panel("donut", (1260, 452, 472, 250), "Count coverage", "stocked items counted",
               {"x-axis": [c("StockItem", "Coverage")], "y-axis": [m("StockItem", "Stocked items")], "centre": [m("StockItem", "Coverage")]},
               unit="items", centreFormat="pct1", centreWord="counted", header="Coverage", valueHeader="Items",
               colours={"Counted": "data-1"})
    page.panel(
        "grid", (384, 718, 1348, 248), "Count variances", "to investigate and adjust",
        {"columns": [c("CountLine", "Item"), c("CountLine", "Warehouse"), c("CountLine", "Count"), c("CountLine", "OnHand"),
                     c("CountLine", "Difference"), c("CountLine", "VarianceNote"), c("CountLine", "VarianceTone")]},
        [where("CountLine", "Result", "eq", "Variance")],
        orderBy=[{"select": 6, "direction": "asc"}, {"select": 4, "direction": "asc"}],
        columns=[
            {"header": "Item"},
            {"header": "Warehouse"},
            {"header": "Count"},
            {"header": "On hand", "align": "right", "format": "whole"},
            {"header": "Difference", "align": "right", "format": "signed"},
            {"header": "Note", "pill": {"toneFrom": 6}},
            {"hidden": True},
        ],
    )
    return page.report("Stock Accuracy & Control", did)


# ---------------------------------------------------------------- W7


def w7_outbound(did: str) -> dict[str, Any]:
    page = Page("w7")
    ys = layout_b(
        page,
        crumb="Warehouse / Outbound",
        title="Outbound & Transfers",
        question="What has been requested, issued and moved, and is it leaving on time?",
        units="Requests · issues · transfers",
        filters=[(c("Warehouse", "Warehouse"), "Warehouse"), (c("RequestType", "RequestType"), "Request type")],
        highlight=["Pick & pack", "Dispatch"],
        notes=CHAIN_NOTES,
    )
    x, w = 40, 316
    on_time = {**higher_is_better(0.95, 0.80), "blank": "none"}
    page.kpi(x, ys[0], w, "Open material requests", m("Request", "Open requests"), rule=WATCH_IF_ANY,
             extra=[m("Request", "Oldest open"), m("Request", "Requests")], extra_formats=["date", "whole"],
             status={"good": "None open", "watch": "Watch"}, context="Oldest {1} · of {2} requests", no_data_if=2,
             context_zero="Of {2} requests")
    page.kpi(x, ys[1], w, "Stock transfers", m("Transfer", "Transfers"), rule={**WATCH_IF_ANY, "zero": "good"},
             extra=[m("Transfer", "Late transfers"), m("Transfer", "In transit")], tone_from=1, no_data_if=0,
             status={"good": "None late", "watch": "{1} late"}, context="{2} in transit · {1} late")
    page.kpi(x, ys[2], w, "Issues", m("Issue", "Issues"), rule=NONE_IF_ZERO, context="Stock issued against requests")
    page.kpi(x, ys[3], w, "Deliveries shipped", m("Delivery", "Shipped"), rule=NONE_IF_ZERO,
             extra=[m("Delivery", "Delivery notes")], status={"none": "No delivery shipped yet"}, context="Of {1} delivery notes")
    page.kpi(x, ys[4], w, "Dispatched on time", m("Delivery", "On time share"), rule=on_time, fmt="pct1",
             status={"none": "Shown once deliveries ship"}, context="Target 95% of shipped deliveries")

    page.panel("flow", (384, 186, 560, 516), "From request to delivery", "documents",
               {"y-axis": [m("Request", "Requests"), m("Issue", "Issues"), m("Transfer", "Transfers"), m("Delivery", "Shipped")]},
               labels=["Requested", "Issued", "Transferred", "Delivered"])
    page.panel("donut", (960, 186, 380, 250), "Material requests by status", "requests",
               {"x-axis": [c("Request", "Status")], "y-axis": [m("Request", "Requests")]},
               unit="requests", header="Status", valueHeader="Requests",
               colours={"Open": "watch", "Closed": "good", "Cancelled": "none"})
    page.panel("meter", (1356, 186, 376, 250), "Dispatched on time", "% of deliveries · target 95%",
               {"y-axis": [m("Delivery", "On time share")]}, target=0.95, rule=on_time, format="pct1",
               blankText="– No deliveries yet")
    page.panel("bars", (960, 452, 772, 250), "Outbound activity", "documents",
               {"y-axis": [m("Request", "Requests"), m("Issue", "Issues"), m("Transfer", "Transfers"), m("Delivery", "Delivery notes")]},
               labels=["Material requests", "Issues", "Stock transfers", "Delivery notes"], unit="documents")
    page.panel(
        "grid", (384, 718, 1348, 248), "Material requests", "open first, then newest",
        {"columns": [c("Request", "Request"), c("Request", "RequestType"), c("Request", "Reference"), c("Request", "Raised"),
                     c("Request", "Status"), c("Request", "StatusOrder")]},
        orderBy=[{"select": 5, "direction": "asc"}, {"select": 3, "direction": "desc"}],
        columns=[
            {"header": "Request"},
            {"header": "Type"},
            {"header": "Reference"},
            {"header": "Raised", "format": "date"},
            {"header": "Status", "pill": {"map": {"Open": "watch", "Closed": "good", "Cancelled": "none"}}},
            {"hidden": True},
        ],
    )
    return page.report("Outbound & Transfers", did)


DASHBOARDS = {"W1": w1_stock_expiry, "W4": w4_accuracy, "W7": w7_outbound}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--data", type=Path, help="reuse an earlier extract folder instead of reading MSD_ERP")
    parser.add_argument("--only", choices=sorted(DASHBOARDS), action="append")
    parser.add_argument("--live", metavar="CONNECTION_ID", help="switch the dataset to read-only queries on this connection and refresh")
    parser.add_argument("--reports-only", action="store_true", help="rewrite the reports on the existing dataset; leave its data alone")
    args = parser.parse_args()
    api = Api(args.api)
    if args.live:
        did = api.dataset(args.workspace, DATASET)
        print(json.dumps({"dataset": did, "refresh": go_live(api, args.workspace, did, args.live)}, indent=1))
        return
    if args.reports_only:
        did = api.dataset(args.workspace, DATASET)
        built = {key: api.save_report(args.workspace, did, DASHBOARDS[key](did)["name"], DASHBOARDS[key](did)) for key in args.only or sorted(DASHBOARDS)}
        print(json.dumps({"dataset": did, "reports": built}, indent=1))
        return
    folder = args.data or Path(tempfile.mkdtemp(prefix="wms-extract-"))
    if args.data is None:
        print(json.dumps(extract(folder), indent=1))
    did = load_dataset(api, args.workspace, folder)
    built = {}
    for key in args.only or sorted(DASHBOARDS):
        definition = DASHBOARDS[key](did)
        built[key] = api.save_report(args.workspace, did, definition["name"], definition)
    print(json.dumps({"dataset": did, "reports": built}, indent=1))


if __name__ == "__main__":
    main()
