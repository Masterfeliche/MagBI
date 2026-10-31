"""Checks a theme must pass before anyone can use it.

- Text is readable: WCAG contrast of every text token on every surface it sits on.
- Chart colours can be told apart, with normal vision and the three kinds of
  colour blindness (OKLab distance x 100 after simulation). A theme whose chart
  colours are one hue in light-to-dark steps (``data.style: "ramp"``) is held
  to a lower floor for normal vision, because its charts always carry labels.
- Statuses stay distinct from each other and are not reused as chart colours.
"""

from __future__ import annotations

import math
from itertools import combinations, pairwise
from typing import Any

# Machado et al. (2009) full-severity simulation matrices, in linear RGB.
CVD = {
    "protanopia": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
    "deuteranopia": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
    "tritanopia": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602), (0.004733, 0.691367, 0.303900)),
}
# Neighbouring chart colours: the dataviz floor is 15 with normal vision; under
# colour blindness 8 is the target and 6 the floor, legal only with labels.
NORMAL_MIN = 15.0
RAMP_MIN = 8.0
CVD_MIN = 6.0
STATUS_MIN = 12.0
TEXT_ON = ("page", "panel", "frame", "strip")
ALERTS = ("good", "watch", "action")


def _hex(colour: str) -> tuple[float, float, float]:
    value = colour.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def contrast(a: str, b: str) -> float:
    """WCAG 2 contrast ratio of two hex colours."""

    def luminance(colour: str) -> float:
        r, g, b = (_linear(c) for c in _hex(colour))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _oklab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = rgb
    lms = (
        0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b,
        0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b,
        0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b,
    )
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in lms)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def distance(a: str, b: str, vision: str = "normal") -> float:
    """OKLab distance x 100 between two colours as seen with ``vision``."""

    def seen(colour: str) -> tuple[float, float, float]:
        rgb = tuple(_linear(c) for c in _hex(colour))
        if vision in CVD:
            rgb = tuple(min(1.0, max(0.0, sum(m * c for m, c in zip(row, rgb, strict=True)))) for row in CVD[vision])
        return _oklab(rgb)  # type: ignore[arg-type]

    return 100 * math.dist(seen(a), seen(b))


def problems(theme: dict[str, Any]) -> list[str]:
    """Every rule the theme breaks; empty when it passes."""
    found: list[str] = []
    need = float(theme.get("accessibility", {}).get("contrast", 4.5))
    surface, text, status = theme["surface"], theme["text"], theme["status"]

    def readable(fg: str, bg: str, label: str, minimum: float = need) -> None:
        ratio = contrast(fg, bg)
        if ratio < minimum:
            found.append(f"{label}: contrast {ratio:.2f} is under {minimum}")

    for where in TEXT_ON:
        for name in ("ink", "muted", "caption"):
            readable(text[name], surface[where], f"text.{name} on surface.{where}")
    readable(text["accent"], surface["page"], "text.accent on surface.page")
    for tone, token in status.items():
        readable(token["ink"], token["soft"], f"status.{tone}.ink on its soft")
        readable(token["ink"], surface["panel"], f"status.{tone}.ink on surface.panel")
    readable(text["onData"], theme["data"]["categorical"][0], "text.onData on the first chart colour", 3.0)

    colours = theme["data"]["categorical"]
    floor = RAMP_MIN if theme["data"].get("style") == "ramp" else NORMAL_MIN
    for a, b in pairwise(colours):
        if distance(a, b) < floor:
            found.append(f"chart colours {a} and {b} are too alike ({distance(a, b):.1f})")
        for vision in CVD:
            if distance(a, b, vision) < CVD_MIN:
                found.append(f"chart colours {a} and {b} are too alike with {vision} ({distance(a, b, vision):.1f})")

    for a, b in combinations(ALERTS, 2):
        if distance(status[a]["color"], status[b]["color"]) < STATUS_MIN:
            found.append(f"status {a} and {b} look the same")
    for tone in ALERTS:
        for colour in colours:
            if distance(status[tone]["color"], colour) < STATUS_MIN:
                found.append(f"status {tone} {status[tone]['color']} is reused as chart colour {colour}")
    return found
