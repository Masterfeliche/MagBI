"""Read the Warehouse tables from MSD_ERP, read-only, into CSV files.

The credential stays in a local env file (``MAGBI_MSD_ENV``, keys SSRS_DB_*),
never in code or output. Only MSD_ERP is accepted.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import re
import time
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyodbc

from magbi.connectors.readonly import check_read_only
from scripts.wms.queries import QUERIES

# Dimension tables shared by every fact, so one filter reaches them all.
DIMENSIONS = {
    "Warehouse": ("Warehouse", ["Batch", "StockLine", "FEFO", "Chain", "CountLine", "StockItem", "Movement", "Adjustment", "Request", "Issue", "Transfer", "Delivery"]),
    "Category": ("Category", ["Batch", "StockLine", "FEFO", "CountLine"]),
    "RequestType": ("RequestType", ["Request", "Issue"]),
}


def table_name(key: str) -> str:
    """'W1.Batch' -> 'Batch'."""
    return key.split(".", 1)[-1]


def _env(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in path.read_text().splitlines():
        match = re.match(r'^\s*([A-Z_]+)\s*=\s*"?(.*?)"?\s*$', line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def connect(env_file: Path) -> pyodbc.Connection:
    cfg = _env(env_file)
    if cfg.get("SSRS_DB_NAME", "").upper() != "MSD_ERP":
        raise SystemExit("refusing: the configured database is not MSD_ERP")
    parts = [
        "DRIVER={ODBC Driver 18 for SQL Server}",
        f"SERVER={cfg['SSRS_DB_SERVER']}",
        "DATABASE=MSD_ERP",
        "TrustServerCertificate=yes",
        "ApplicationIntent=ReadOnly",
    ]
    if cfg.get("SSRS_DB_USER"):
        parts += [f"UID={cfg['SSRS_DB_USER']}", f"PWD={cfg['SSRS_DB_PASS']}"]
    else:
        parts.append("Trusted_Connection=yes")
    return pyodbc.connect(";".join(parts), timeout=15, autocommit=False)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time() else value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _write(path: Path, header: list[str], rows: Iterable[Iterable[Any]]) -> int:
    count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow([_cell(value) for value in row])
            count += 1
    return count


def extract(out_dir: Path, env_file: Path | None = None) -> dict[str, dict[str, Any]]:
    """Write one CSV per table and per dimension. Returns rows and seconds per table."""
    env = env_file or Path(os.environ["MAGBI_MSD_ENV"])
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, dict[str, Any]] = {}
    values: dict[str, set[str]] = {name: set() for name in DIMENSIONS}
    con = connect(env)
    try:
        for key, sql in QUERIES.items():
            name = table_name(key)
            started = time.perf_counter()
            cursor = con.cursor()
            cursor.execute(check_read_only(sql))
            header = [column[0] for column in cursor.description]
            rows = [tuple(row) for row in cursor.fetchall()]
            cursor.close()
            con.rollback()
            seconds = time.perf_counter() - started
            for dim, (column, facts) in DIMENSIONS.items():
                if name in facts and column in header:
                    at = header.index(column)
                    values[dim].update(_cell(row[at]) or "Not set" for row in rows)
            report[name] = {"rows": _write(out_dir / f"{name}.csv", header, rows), "seconds": round(seconds, 3)}
    finally:
        con.close()
    for dim, (column, _facts) in DIMENSIONS.items():
        members = sorted(values[dim] | {"Not set"})
        report[dim] = {"rows": _write(out_dir / f"{dim}.csv", [column], ([member] for member in members)), "seconds": 0}
    return report
