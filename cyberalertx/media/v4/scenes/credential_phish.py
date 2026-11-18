"""Credential phishing: a sign-in card (a generic one: two fields, the
password masked) caught on a large fishing hook and pulled up out of the
water on a taut line. When the sources describe the lure as an email or a
notification, an envelope hangs on the line above the hook as the bait.
When they report a takedown or seizure, the line is cut.

Different from `session_theft` on purpose: no relay, no token; the subject
is the lure and the password itself. No look-alike domain, no capture log,
no names: nothing the sources do not state."""
from __future__ import annotations

import random
import re

from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f
from . import scene
from ._editorial import fit_size


def _card(doc: Doc, hx: float, hy: float, rot: float, accent: str, danger: str) -> None:
    """The card hangs from a hole at its top centre, at (hx, hy)."""
    w, h = 540.0, 400.0
    x, y = hx - w / 2, hy - 40
    with doc.g(f"rotate({f(rot)} {f(hx)} {f(hy)})"):
        doc.rect(x + 16, y + 30, w, h, "#000", 22, opacity=0.18, extra=f' filter="{doc.blur(16)}"')
        doc.rect(x, y, w, h, "#FFFFFF", 22, stroke="#B3C2D0", sw=2)
        # avatar and title bar (placeholders, no text)
        doc.circle(x + 66, y + 78, 26, "#DCE5EC")
        doc.rect(x + 108, y + 68, 120, 20, "#C5D3DF", 10)
        # username field: placeholder bar
        doc.rect(x + 40, y + 130, w - 80, 70, "#F3F6F9", 12, stroke="#B3C2D0", sw=2)
        doc.rect(x + 66, y + 158, 220, 14, "#B3C2D0", 7)
        # password field: masked, in the danger colour (what the lure takes)
        doc.rect(x + 40, y + 226, w - 80, 70, "#FFF4F2", 12, stroke=danger, sw=4)
        for k in range(8):
            doc.circle(x + 80 + k * 42, y + 261, 12, danger)
        doc.rect(x + 40, y + 322, w - 80, 52, accent, 12)
        # the hole the hook went through
        doc.circle(hx, hy, 16, "#5B6B7D")


def _hook(doc: Doc, eye: tuple[float, float], s: float) -> tuple[float, float]:
    """A J hook from its eye down to the point. Returns the point."""
    ex, ey = eye
    steel = "#5B6B7D"
    shank_b = ey + 300 * s
    d = (f"M{f(ex)} {f(ey + 18 * s)}V{f(shank_b)}"
         f"A{f(110 * s)} {f(110 * s)} 0 0 0 {f(ex + 220 * s)} {f(shank_b)}V{f(shank_b - 120 * s)}")
    doc.path(d, stroke="#000", sw=22 * s, opacity=0.18, extra=f' filter="{doc.blur(8)}" transform="translate(10 18)"')
    doc.path(d, stroke=steel, sw=20 * s)
    doc.path(d, stroke="#DCE5EC", sw=6 * s, opacity=0.8)
    px, py = ex + 220 * s, shank_b - 120 * s
    # barb and point
    doc.poly([(px - 10 * s, py + 6 * s), (px + 10 * s, py + 6 * s), (px, py - 40 * s)], steel)
    doc.poly([(px - 9 * s, py + 30 * s), (px - 34 * s, py + 2 * s), (px - 9 * s, py + 6 * s)], steel)
    doc.circle(ex, ey, 18 * s, "none", steel, 9 * s)
    return px, py


@scene("credential_phish")
def credential_phish(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    background(doc, light=(0.5, 0.1))
    seized = re.search(r"takes? down|takedown|seiz|dismantl|ліквід|вилуч", text) is not None
    lure = re.search(r"e-?mail|notification|сповіщен|розсил|лист", text) is not None
    # water at the bottom, the card lifted out of it
    wy = 800.0
    doc.rect(0, wy, 1600, 900 - wy, doc.lin([(0, "#8FB3D1", 0.55), (1, "#5B86AD", 0.75)]))
    for k in range(7):
        doc.add(f'<ellipse cx="{f(860 + (k % 2) * 30)}" cy="{f(wy + 6)}" rx="{f(90 + k * 70)}" '
                f'ry="{f(10 + k * 6)}" fill="none" stroke="#FFFFFF" stroke-width="3" opacity="{0.7 - k * 0.09:.2f}"/>')
    # the line from above
    ex, ey = 900.0, 80.0
    if seized:
        doc.line((ex, -10), (ex, ey - 120), "#3A4756", 3)
        doc.path(f"M{f(ex)} {f(ey - 60)}l-14 -18M{f(ex)} {f(ey - 60)}l14 -18", stroke=p.danger, sw=4)
        doc.line((ex, ey - 50), (ex, ey - 18), "#3A4756", 3)
    else:
        doc.line((ex, -10), (ex, ey - 18), "#3A4756", 3)
    if lure:      # the bait: an envelope tied on the line
        bx, by = ex - 250, 120.0
        doc.line((ex, by - 80), (bx + 90, by + 4), "#3A4756", 2)
        with doc.g(f"rotate(-10 {f(bx + 90)} {f(by + 60)})"):
            doc.rect(bx + 8, by + 16, 180, 120, "#000", 8, opacity=0.15, extra=f' filter="{doc.blur(8)}"')
            doc.rect(bx, by, 180, 120, "#FFFFFF", 8, stroke="#B3C2D0", sw=2)
            doc.path(f"M{f(bx)} {f(by)}L{f(bx + 90)} {f(by + 66)}L{f(bx + 180)} {f(by)}", stroke="#5B6B7D", sw=4)
    # the card hanging from the hook's bend, pulled up out of the water
    _card(doc, ex + 110, ey + 300 + 104, 7, p.accent, p.danger)
    _hook(doc, (ex, ey), 1.0)
    doc.rect(0, wy, 1600, 900 - wy, doc.lin([(0, "#8FB3D1", 0.55), (1, "#5B86AD", 0.8)]))
    doc.line((0, wy), (1600, wy), "#FFFFFF", 3, 0.7)
    if "microsoft 365" in text:
        size = fit_size("Microsoft 365", 54, 520, "display")
        doc.text("Microsoft 365", 110, 200, size, p.ink, "display")
    doc.focus = Box(80, 50, 1340, 754)
    _ = rng
