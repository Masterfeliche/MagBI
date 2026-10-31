"""A single-value visual's query, built on the server the way the web app builds it.

Alerts are checked after a refresh, with no browser open, so the server reads
the visual's Value well and the report, page and visual filters itself
(web/src/designer/query.ts does the same in the browser).
"""

from __future__ import annotations

from typing import Any

# Visuals that show one number; their first value is what an alert watches.
ALERTABLE = ("card", "kpi", "gauge")
_OPERATORS = ("eq", "ne", "gt", "gte", "lt", "lte", "in", "contains", "startsWith")


def find_visual(
    definition: dict[str, Any], visual_id: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """The page and visual with this id, or None."""
    for page in definition.get("pages") or []:
        for visual in page.get("visuals") or []:
            if visual.get("id") == visual_id:
                return page, visual
    return None


def visual_title(visual: dict[str, Any]) -> str:
    properties = visual.get("properties") or {}
    title = properties.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    binding = _value_binding(visual) or {}
    return str(binding.get("measure") or binding.get("column") or "Card")


def _value_binding(visual: dict[str, Any]) -> dict[str, Any] | None:
    wells = visual.get("wells") or {}
    for binding in wells.get("y-axis") or wells.get("values") or []:
        if (
            isinstance(binding, dict)
            and binding.get("table")
            and (binding.get("measure") or binding.get("column"))
        ):
            return binding
    return None


def _where(filters: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in filters:
        if (
            not isinstance(item, dict)
            or item.get("type") != "basic"
            or not isinstance(item.get("config"), dict)
        ):
            continue
        values = item["config"].get("values")
        if not isinstance(values, list) or not values:
            continue
        operator = item["config"].get("operator")
        out.append(
            {
                "column": {"table": item.get("table"), "column": item.get("column")},
                "operator": operator if operator in _OPERATORS else "eq",
                "values": values,
            }
        )
    return out


def value_query(definition: dict[str, Any], visual_id: str) -> dict[str, Any]:
    """The semantic query for the visual's value. Raises ``ValueError`` when it has none."""
    found = find_visual(definition, visual_id)
    if found is None:
        raise ValueError("that visual is no longer in the report")
    page, visual = found
    if visual.get("type") not in ALERTABLE:
        raise ValueError("alerts can watch cards, KPI cards and gauges only")
    binding = _value_binding(visual)
    if binding is None:
        raise ValueError("this visual has no value to watch")
    if binding.get("measure"):
        select: dict[str, Any] = {
            "measure": {"table": binding["table"], "measure": binding["measure"]}
        }
    else:
        select = {
            "column": {"table": binding["table"], "column": binding["column"]},
            "aggregation": binding.get("aggregation") or "sum",
        }
    filters = [
        *(definition.get("filters") or []),
        *(page.get("filters") or []),
        *(visual.get("filters") or []),
    ]
    query: dict[str, Any] = {"from": [], "select": [select]}
    where = _where(filters)
    if where:
        query["where"] = where
    return query
