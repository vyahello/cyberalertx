"""Text as vector paths.

Glyph outlines of the fonts the site itself uses (Space Grotesk, Fira Sans
Condensed) plus Geist Mono for code, extracted once by
ops/media/build_glyphs.py into glyphs.json. Setting text as paths keeps the
images identical on every machine (no font lookup when the SVG is rasterized)
and keeps the sanitizer's rule that an image carries no <text> element.

Only the printable ASCII range and a few symbols are available: image text is
language-neutral by design (code, domains, numbers, identifiers), because one
illustration serves both the EN and the UA edition.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_CMD = re.compile(r"([MLQCZHV])([^MLQCZHV]*)")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


@lru_cache(maxsize=1)
def _fonts() -> dict[str, dict[str, Any]]:
    raw = json.loads((Path(__file__).with_name("glyphs.json")).read_text(encoding="utf-8"))
    fonts: dict[str, dict[str, Any]] = {}
    for key, f in raw["fonts"].items():
        glyphs = {}
        for ch, (adv, d) in f["glyphs"].items():
            cmds = [(c, [float(v) for v in _NUM.findall(args)]) for c, args in _CMD.findall(d)]
            glyphs[ch] = (adv, cmds)
        fonts[key] = {**f, "glyphs": glyphs}
    return fonts


def supported(s: str, font: str = "ui") -> str:
    """`s` without the characters the font cannot set (non-Latin text is dropped
    rather than drawn as empty boxes)."""
    g = _fonts()[font]["glyphs"]
    return "".join(ch for ch in s if ch in g)


def measure(s: str, size: float, font: str = "ui", tracking: float = 0.0) -> float:
    g = _fonts()[font]["glyphs"]
    units = float(sum(g[ch][0] for ch in s if ch in g))
    n = sum(1 for ch in s if ch in g)
    return units * size / 1000 + tracking * max(n - 1, 0)


def fit(s: str, size: float, max_w: float, font: str = "ui") -> str:
    """Truncate with an ellipsis so the run fits `max_w`."""
    s = supported(s, font)
    if measure(s, size, font) <= max_w:
        return s
    while s and measure(s + "…", size, font) > max_w:
        s = s[:-1]
    return s.rstrip() + "…"


def _n(v: float) -> str:
    return str(int(round(v)))


def text_path(s: str, x: float, y: float, size: float, *, font: str = "ui", fill: str = "#fff",
              anchor: str = "start", tracking: float = 0.0, opacity: float = 1.0) -> tuple[str, float]:
    """One <path> for the whole run; `y` is the baseline. Returns (svg, width)."""
    f = _fonts()[font]
    g = f["glyphs"]
    s = supported(s, font)
    width = measure(s, size, font, tracking)
    if anchor == "middle":
        x -= width / 2
    elif anchor == "end":
        x -= width
    k = size / 1000
    track_units = tracking / k if k else 0.0
    pen = 0.0
    out: list[str] = []
    for ch in s:
        adv, cmds = g[ch]
        for c, nums in cmds:
            if c == "Z":
                out.append("Z")
            elif c == "H":
                out.append("H" + " ".join(_n(v + pen) for v in nums))
            elif c == "V":
                out.append("V" + " ".join(_n(v) for v in nums))
            else:
                out.append(c + " ".join(_n(v + pen) if i % 2 == 0 else _n(v) for i, v in enumerate(nums)))
        pen += adv + track_units
    if not out:
        return "", width                 # whitespace still advances the pen
    op = f' opacity="{opacity:.2f}"' if opacity < 1 else ""
    svg = (f'<path transform="translate({x:.1f} {y:.1f}) scale({k:.4f} {-k:.4f})" fill="{fill}"{op} '
           f'd="{"".join(out)}"/>')
    return svg, width


def line_height(size: float, font: str = "ui") -> float:
    f = _fonts()[font]
    return float(f["ascender"] - f["descender"]) * size / 1000


def cap_height(size: float, font: str = "ui") -> float:
    return float(_fonts()[font]["cap"]) * size / 1000
