"""MagBI dashboard library: the MSD frame, the standard visuals, and the API calls.

The MagBI counterpart of ``bi_lib.py``. Standing rules live here so every
dashboard gets them: ERP Native theme, 1760 x 990 canvas, KPI cards of 124 px,
status from tone rules, no-data members grey, "–" for blanks.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PAGE_W, PAGE_H = 1760, 990
PAGE_BG = "#EEF2F7"
DATA = ["#3F6FB0", "#5F8BC9", "#82A6D6", "#B3C3D8"]
KPI_H = 124

# ---------------------------------------------------------------- tone rules

INFO = {"blank": "none", "otherwise": "info"}
WATCH_IF_ANY = {"blank": "none", "zero": "good", "otherwise": "watch"}
ACTION_IF_ANY = {"blank": "none", "zero": "good", "otherwise": "action"}
NONE_IF_ZERO = {"blank": "none", "zero": "none", "otherwise": "info"}


def higher_is_better(watch_below: float, action_below: float) -> dict[str, Any]:
    return {"blank": "none", "steps": [{"min": watch_below, "tone": "good"}, {"min": action_below, "tone": "watch"}], "otherwise": "action"}


# ---------------------------------------------------------------- bindings


def m(table: str, measure: str) -> dict[str, str]:
    return {"table": table, "measure": measure}


def c(table: str, column: str) -> dict[str, str]:
    return {"table": table, "column": column}


def where(table: str, column: str, operator: str, *values: Any) -> dict[str, Any]:
    return {"table": table, "column": column, "type": "basic", "config": {"operator": operator, "values": list(values)}}


# ---------------------------------------------------------------- page


@dataclass
class Page:
    name: str
    visuals: list[dict[str, Any]] = field(default_factory=list)

    def add(self, kind: str, x: int, y: int, w: int, h: int, wells: dict[str, list[dict[str, Any]]] | None = None,
            filters: list[dict[str, Any]] | None = None, **props: Any) -> dict[str, Any]:
        visual = {
            "id": f"{self.name}-{len(self.visuals) + 1:02d}-{kind}",
            "type": kind,
            "x": x, "y": y, "width": w, "height": h,
            "wells": wells or {},
            "properties": props,
        }
        if filters:
            visual["filters"] = filters
        self.visuals.append(visual)
        return visual

    def report(self, title: str, dataset_id: str) -> dict[str, Any]:
        return {
            "schemaVersion": "1.0",
            "name": title,
            "datasetId": dataset_id,
            "theme": {"colors": DATA, "background": PAGE_BG},
            "pages": [{"name": self.name, "displayName": title, "width": PAGE_W, "height": PAGE_H, "visuals": self.visuals}],
        }

    # -- frame ---------------------------------------------------------

    def header(self, crumb: str, title: str, question: str, units: str, source: str = "MSD ERP") -> None:
        self.add("header", 28, 14, 1704, 88, crumb=crumb, title=title, question=question, units=units, source=source)

    def frame(self, x: int, y: int, w: int, h: int, fill: str = "#F8FAFC", border: str = "#D3DCE6", radius: int = 6) -> None:
        self.add("frame", x, y, w, h, fill=fill, border=border, radius=radius)

    def label(self, x: int, y: int, w: int, text: str, h: int = 22, variant: str = "section") -> None:
        self.add("label", x, y, w, h, text=text, variant=variant)

    def dropdown(self, x: int, y: int, w: int, column: dict[str, str], caption: str, hide: tuple[str, ...] = ("Not set",)) -> None:
        self.add("slicer", x, y, w, 52, {"field": [column]}, caption=caption, slicerMode="dropdown", box=True, hide=list(hide))

    def chain(self, x: int, y: int, w: int, highlight: list[str], notes: dict[str, str] | None = None) -> None:
        self.add(
            "chain", x, y, w, 52,
            {
                "x-axis": [c("Chain", "Stage")],
                "columns": [c("Chain", "StageOrder"), c("Chain", "Unit"), c("Chain", "BaseTone"), c("Chain", "FlagTone"), c("Chain", "AgeLimit")],
                "y-axis": [m("Chain", "Chain count"), m("Chain", "Chain age"), m("Chain", "Chain flags")],
            },
            allMembers=True, highlight=highlight, notes=notes or {},
        )

    def kpi(self, x: int, y: int, w: int, caption: str, value: dict[str, str], *, rule: dict[str, Any],
            extra: list[dict[str, str]] | None = None, fmt: str = "whole", extra_formats: list[str] | None = None,
            status: dict[str, str] | None = None, context: str = "", context_zero: str | None = None,
            tone_from: int | None = None, h: int = KPI_H) -> None:
        props: dict[str, Any] = {"caption": caption, "rule": rule, "format": fmt, "extraFormats": extra_formats or [],
                                 "status": status or {}, "context": context}
        if context_zero is not None:
            props["contextZero"] = context_zero
        if tone_from is not None:
            props["toneFrom"] = tone_from
        self.add("kpi", x, y, w, h, {"y-axis": [value], "extra": extra or []}, **props)

    # -- body panels ---------------------------------------------------

    def panel(self, kind: str, box: tuple[int, int, int, int], title: str, subtitle: str,
              wells: dict[str, list[dict[str, Any]]], filters: list[dict[str, Any]] | None = None, **props: Any) -> None:
        x, y, w, h = box
        self.add(kind, x, y, w, h, wells, filters, title=title, subtitle=subtitle, **props)


# ---------------------------------------------------------------- frames


def layout_a(page: Page, *, crumb: str, title: str, question: str, units: str,
             filters: list[tuple[dict[str, str], str]], highlight: list[str], notes: dict[str, str]) -> list[int]:
    """Header, filter box with the chain, and a row of five KPI cards. Returns the card x positions."""
    page.header(crumb, title, question, units)
    page.frame(28, 104, 1704, 66)
    for index, (column, caption) in enumerate(filters):
        page.dropdown(42 + 216 * index, 111, 200, column, caption)
    page.chain(474, 111, 1244, highlight, notes)
    return [28 + 344 * index for index in range(5)]


def layout_b(page: Page, *, crumb: str, title: str, question: str, units: str,
             filters: list[tuple[dict[str, str], str]], highlight: list[str], notes: dict[str, str]) -> list[int]:
    """Header, a side rail with filters and five stacked KPI cards, the chain above the panels.

    Returns the card y positions.
    """
    page.header(crumb, title, question, units)
    page.frame(28, 104, 340, 862)
    page.label(40, 112, 316, "Filters")
    for index, (column, caption) in enumerate(filters):
        page.dropdown(40, 138 + 60 * index, 316, column, caption)
    page.frame(40, 262, 316, 1, fill="#D3DCE6", border="#D3DCE6", radius=0)
    page.label(40, 268, 316, "Key figures")
    page.frame(384, 104, 1348, 66)
    page.chain(398, 111, 1320, highlight, notes)
    return [294 + 134 * index for index in range(5)]


CHAIN_NOTES = {
    "Inbound": "Arrival notes have no warehouse in the ERP, so this box reads 0 when a warehouse is picked",
    "Quality": "QC requests have no warehouse in the ERP, so this box reads 0 when a warehouse is picked",
    "Dispatch": "Delivery notes have no warehouse in the ERP, so this box reads 0 when a warehouse is picked",
}


# ---------------------------------------------------------------- API


class Api:
    def __init__(self, base: str = "http://127.0.0.1:8000/api/v1", token: str | None = None) -> None:
        self.base = base.rstrip("/")
        self.token = token

    def _send(self, method: str, path: str, body: bytes | None, content_type: str | None) -> Any:
        request = urllib.request.Request(self.base + path, data=body, method=method)
        if content_type:
            request.add_header("Content-Type", content_type)
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{method} {path}: {exc.code} {exc.read().decode('utf-8', 'replace')}") from None
        return json.loads(raw) if raw else None

    def get(self, path: str) -> Any:
        return self._send("GET", path, None, None)

    def post(self, path: str, body: Any) -> Any:
        return self._send("POST", path, json.dumps(body).encode(), "application/json")

    def put(self, path: str, body: Any) -> Any:
        return self._send("PUT", path, json.dumps(body).encode(), "application/json")

    def upload(self, path: str, file: Path, table: str) -> Any:
        boundary = uuid.uuid4().hex
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"table_name\"\r\n\r\n{table}\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{file.name}\"\r\n"
            "Content-Type: text/csv\r\n\r\n".encode() + file.read_bytes() + b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        return self._send("POST", path, b"".join(parts), f"multipart/form-data; boundary={boundary}")

    def query(self, wid: str, did: str, query: dict[str, Any]) -> Any:
        return self.post(f"/workspaces/{wid}/datasets/{did}/query", {"query": query})

    def dataset(self, wid: str, name: str) -> str:
        for item in self.get(f"/workspaces/{wid}/datasets"):
            if item["name"] == name:
                return str(item["id"])
        return str(self.post(f"/workspaces/{wid}/datasets", {"name": name})["id"])

    def save_report(self, wid: str, did: str, title: str, definition: dict[str, Any]) -> str:
        for item in self.get(f"/workspaces/{wid}/reports"):
            if item["name"] == title:
                self.put(f"/workspaces/{wid}/reports/{item['id']}", {"definition": definition, "is_published": True})
                return str(item["id"])
        created = self.post(f"/workspaces/{wid}/reports", {"name": title, "dataset_id": did, "definition": definition, "is_published": True})
        return str(created["id"])
