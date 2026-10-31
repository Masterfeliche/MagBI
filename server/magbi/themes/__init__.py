"""Built-in report themes (``magbi.theme/1``), one JSON file each.

These files are the only copy: the web app bundles them, and the dashboard
builder and the QA gate read them through this module.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
DEFAULT_THEME = "enterprise-light"
SECTIONS = ("surface", "text", "data", "status", "type", "shape")
TONES = ("good", "watch", "action", "none", "info")
_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}\b")


def merge(base: dict[str, Any], layer: dict[str, Any]) -> dict[str, Any]:
    """``layer`` over ``base``, nested objects merged and lists replaced."""
    out = dict(base)
    for key, value in layer.items():
        out[key] = merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


@cache
def _all() -> dict[str, dict[str, Any]]:
    raw = {}
    for path in sorted(HERE.glob("*.json")):
        theme = json.loads(path.read_text(encoding="utf-8"))
        raw[theme["id"]] = theme

    def full(theme_id: str) -> dict[str, Any]:
        theme = raw[theme_id]
        parent = theme.get("extends")
        return merge(full(parent), theme) if parent else theme

    # The default theme comes first; the gallery keeps this order.
    order = [DEFAULT_THEME, *sorted(raw.keys() - {DEFAULT_THEME}, key=lambda key: raw[key].get("order", 99))]
    return {theme_id: full(theme_id) for theme_id in order}


def theme_ids() -> list[str]:
    return list(_all())


def load_theme(theme_id: str = DEFAULT_THEME) -> dict[str, Any]:
    """A built-in theme by id; raises ``KeyError`` for an unknown id."""
    return _all()[theme_id]


def theme_colours(theme: dict[str, Any]) -> set[str]:
    """Every hex colour a theme defines, upper case."""
    return {item.upper() for item in _COLOUR.findall(json.dumps(theme))}


def token_names(theme: dict[str, Any]) -> dict[str, str]:
    """Surface and text token names a visual may store instead of a hex, mapped to their colour."""
    names = {**theme["text"], **theme["surface"]}
    return {name: value for name, value in names.items() if isinstance(value, str) and _COLOUR.fullmatch(value)}


def missing_tokens(theme: dict[str, Any]) -> list[str]:
    """Sections and statuses a complete theme needs but this one lacks."""
    missing = [section for section in SECTIONS if section not in theme]
    missing += [f"status.{tone}" for tone in TONES if tone not in theme.get("status", {})]
    if not theme.get("data", {}).get("categorical"):
        missing.append("data.categorical")
    return missing


def tokenise_definition(definition: dict[str, Any], theme: dict[str, Any]) -> int:
    """Swap literal colours for theme names, in place: frame colours that equal a
    surface token become its name, pinned category colours that equal a chart
    colour become ``data-N``.

    Returns how many colours changed. A colour no token matches stays a literal override.
    """
    by_colour: dict[str, str] = {}
    for name, value in theme["surface"].items():
        if isinstance(value, str) and _COLOUR.fullmatch(value):
            by_colour.setdefault(value.upper(), name)
    by_position = {value.upper(): f"data-{index + 1}" for index, value in enumerate(theme["data"]["categorical"])}
    changed = 0
    for page in definition.get("pages", []):
        for visual in page.get("visuals", []):
            props = visual.setdefault("properties", {})
            if visual.get("type") == "frame":
                for key in ("fill", "border"):
                    value = props.get(key)
                    if isinstance(value, str) and value.upper() in by_colour:
                        props[key] = by_colour[value.upper()]
                        changed += 1
            # Pinned category colours that equal a chart colour follow the theme by position.
            pinned = props.get("colours")
            if isinstance(pinned, dict):
                for name, value in pinned.items():
                    if isinstance(value, str) and value.upper() in by_position:
                        pinned[name] = by_position[value.upper()]
                        changed += 1
    theme_field = definition.setdefault("theme", {})
    if "id" not in theme_field:
        theme_field["id"] = theme["id"]
        changed += 1
    return changed
