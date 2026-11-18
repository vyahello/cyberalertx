"""Supercomputer stories.

With a verified library photograph of the named system (Tier A), the image is
that photograph — graded, never altered in content — plus a restrained
news-graphic annotation: a marker on the machine and the account figure the
headline states. Without one, `hpc_drawn` draws a machine hall in one-point
perspective (scenes/hpc_drawn.py)."""
from __future__ import annotations

import random
import re

from .. import library
from ..brief import EditorialBrief
from ..kit import H, W, Box, Doc, f, icon
from . import SCENES, scene


def _bracket(doc: Doc, x0: float, y0: float, x1: float, y1: float, color: str, arm: float = 34) -> None:
    for (cx, cy, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        doc.path(f"M{f(cx)} {f(cy + dy * arm)}V{f(cy)}H{f(cx + dx * arm)}", stroke=color, sw=4, cap="square",
                 join="miter")


def _account_panel(doc: Doc, x: float, y: float, brief: EditorialBrief) -> tuple[float, float]:
    """Dark glass panel: the account figure from the headline and a grid of
    account chips, most of them flagged. Returns the panel's anchor point."""
    p = doc.pal
    w, h = 600, 172
    doc.rect(x + 8, y + 18, w, h, "#000", 14, opacity=0.35, extra=f' filter="{doc.blur(16)}"')
    doc.rect(x, y, w, h, "#0A111C", 14, opacity=0.9)
    doc.rect(x, y, w, h, "none", 14, stroke="#FFFFFF", sw=1, opacity=0.14)
    icon(doc, "user", x + 46, y + 62, 40, p.danger, 2.6)
    n = brief.facts.get("accounts")
    if n:
        label = f"{n}+" if brief.facts.get("accounts_plus") else n
        doc.text(label, x + 80, y + 80, 58, "#FFFFFF", "display")
    else:
        doc.text("accounts", x + 80, y + 76, 40, "#FFFFFF", "display")
    # chips: a visual token for "accounts" (not a count), most of them marked
    cols, rows = 14, 2
    cx0, cy0 = x + 34, y + 116
    for r in range(rows):
        for c in range(cols):
            hit = (r * cols + c) % 7 != 3
            px, py = cx0 + c * 39, cy0 + r * 24
            doc.rect(px, py, 31, 16, p.danger if hit else "#2B3A50", 4, opacity=0.95 if hit else 1)
    return x, y + h / 2


def _state_panel(doc: Doc, x: float, y: float, brief: EditorialBrief) -> tuple[float, float]:
    """What the sources say happened to the machine, when no account figure is
    given: taken offline, or (otherwise) a security breach."""
    p = doc.pal
    offline = bool(re.search(r"offline|offlline|shut down|вимкн|відключ", brief.text))
    label = "OFFLINE" if offline else "BREACH"
    w, h = 480, 120
    doc.rect(x + 8, y + 18, w, h, "#000", 14, opacity=0.35, extra=f' filter="{doc.blur(16)}"')
    doc.rect(x, y, w, h, "#0A111C", 14, opacity=0.9)
    doc.rect(x, y, w, h, "none", 14, stroke="#FFFFFF", sw=1, opacity=0.14)
    if offline:
        # power symbol
        doc.path(f"M{x + 62} {y + 34}V{y + 60}", stroke=p.danger, sw=5)
        doc.path(f"M{x + 46} {y + 42}A24 24 0 1 0 {x + 78} {y + 42}", stroke=p.danger, sw=5)
    else:
        icon(doc, "warn", x + 62, y + 60, 46, p.danger, 2.8)
    doc.text(label, x + 112, y + 80, 54, "#FFFFFF", "display", tracking=2)
    return x, y + h / 2


@scene("hpc_hall")
def hpc_hall(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    lib = library.get(brief.library_id) if brief.library_id else None
    if lib is None:
        SCENES["hpc_drawn"](doc, brief, rng)
        return
    p = doc.pal
    doc.add(f'<image x="0" y="0" width="{W}" height="{H}" preserveAspectRatio="xMidYMid slice" '
            f'href="{lib.data_uri()}"/>')
    # Editorial grade: cooler, darker toward the floor and the ceiling, so the
    # lit racks carry the frame and the annotation stays legible.
    doc.rect(0, 0, W, H, "#0B1A33", opacity=0.12)
    doc.rect(0, 0, W, H, doc.lin([(0, "#050A14", 0.5), (0.3, "#050A14", 0.0), (0.72, "#050A14", 0.0),
                                  (1, "#050A14", 0.42)]))
    # The machine: marker around the rack row in focus.
    rx0, ry0, rx1, ry1 = lib.marker
    _bracket(doc, rx0, ry0, rx1, ry1, p.danger)
    if brief.facts.get("accounts") or re.search(r"accounts|обліков", brief.text):
        ax, ay = _account_panel(doc, 940, 34, brief)
    else:
        ax, ay = _state_panel(doc, 1060, 34, brief)
    doc.path(f"M{rx1 + 6} {ry0 + 40}L{ax - 70} {ry0 + 40}L{ax} {ay}", stroke=p.danger, sw=2.5, dash="8 7")
    doc.circle(ax, ay, 6, p.danger)
    doc.focus = Box(430, 20, 1150, 647)          # the marked rack row and the account figure
