"""Headline figures read straight from MSD_ERP, for the QA gate to hold MagBI against.

Written as plain aggregates, separately from the extract queries, so a mistake in
the extract, the upload, the model or the engine shows up as a difference.

    MAGBI_MSD_ENV=<path to .env.db> python -m scripts.wms.expected <out.json>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from magbi.connectors.readonly import check_read_only
from scripts.wms.msd_extract import connect

ON_HAND = """
FROM wms.SKUBatch b JOIN wms.SKU s ON s.ID = b.SKUGuid JOIN veims.ItemMaster i ON i.ID = s.ItemGuid
WHERE b.QtyOnHand > 0"""
DAYS = "DATEDIFF(day, CAST(GETDATE() AS date), b.ExpDate)"
CLOSED = "('Closed', 'Completed', 'Issued')"
CANCELLED = "('Cancelled', 'Rejected')"

FIGURES: dict[str, dict[str, str]] = {
    "Stock & Expiry": {
        "Batch|Batches": f"SELECT COUNT(*) {ON_HAND}",
        "Batch|Expiring 90": f"SELECT COUNT(*) {ON_HAND} AND {DAYS} BETWEEN 0 AND 90",
        "Batch|Expired": f"SELECT COUNT(*) {ON_HAND} AND {DAYS} < 0",
        "Batch|No expiry": f"SELECT COUNT(*) {ON_HAND} AND b.ExpDate IS NULL",
        "StockLine|Stock lines": "SELECT COUNT(*) FROM wms.StockOnHand",
        "StockLine|SKUs": "SELECT COUNT(DISTINCT SKUGuid) FROM wms.StockOnHand",
    },
    "Stock Accuracy & Control": {
        "CountLine|Count lines": "SELECT COUNT(*) FROM veims.PhysicalInventoryItem",
        "CountLine|Variances": "SELECT COUNT(*) FROM veims.PhysicalInventoryItem WHERE DifferenceQty <> 0",
        "CountLine|Accuracy": "SELECT CAST(SUM(CASE WHEN DifferenceQty = 0 THEN 1 ELSE 0 END) AS float) / COUNT(*) FROM veims.PhysicalInventoryItem",
        "StockItem|Stocked items": "SELECT COUNT(*) FROM (SELECT DISTINCT ItemGuid, WareHouseGuid FROM wms.StockOnHand WHERE QtyAvailable > 0) s",
        "Movement|Movements": "SELECT COUNT(*) FROM wms.InventoryMovement",
        "Adjustment|Adjustments": "SELECT COUNT(*) FROM wms.ExceptionLog",
    },
    "Outbound & Transfers": {
        "Request|Requests": "SELECT COUNT(*) FROM veims.MaterialRequest",
        "Request|Open requests": f"SELECT COUNT(*) FROM veims.MaterialRequest WHERE VoucherStatus NOT IN {CLOSED} AND VoucherStatus NOT IN {CANCELLED}",
        "Issue|Issues": "SELECT COUNT(*) FROM veims.ItemWithdrawals",
        "Transfer|Transfers": "SELECT COUNT(*) FROM veims.StockTransferOrder",
        "Delivery|Shipped": "SELECT SUM(CASE WHEN Shipped = 1 THEN 1 ELSE 0 END) FROM vesos.DeliveryNote",
    },
}


def read(env_file: Path) -> dict[str, dict[str, float | None]]:
    con = connect(env_file)
    out: dict[str, dict[str, float | None]] = {}
    try:
        for report, figures in FIGURES.items():
            out[report] = {}
            for key, sql in figures.items():
                cursor = con.cursor()
                cursor.execute(check_read_only(sql))
                value = cursor.fetchone()[0]
                cursor.close()
                out[report][key] = None if value is None else float(value)
            con.rollback()
    finally:
        con.close()
    return out


if __name__ == "__main__":
    figures = read(Path(os.environ["MAGBI_MSD_ENV"]))
    Path(sys.argv[1]).write_text(json.dumps(figures, indent=1), encoding="utf-8")
    print(json.dumps(figures, indent=1))
