"""Self-hosted versus SaaS (analysis, no incident): a balance scale weighing
the company's own server cabinet against a cloud service. The scale is
level: the column weighs the choice, it does not give a verdict, and no
"who controls what" ledger is drawn (the sources do not tabulate one).
Labels are the two terms of the headline."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, vignette
from . import scene
from ._editorial import rack_unit


def _cabinet(doc: Doc, x: float, y: float, w: float, h: float, rng: random.Random) -> None:
    """A floor-standing server cabinet, front elevation, door open."""
    doc.add(f'<ellipse cx="{x + w / 2}" cy="{y + h + 6}" rx="{w * 0.6}" ry="12" fill="#000" opacity="0.25" '
            f'filter="{doc.blur(8)}"/>')
    doc.rect(x, y, w, h, doc.lin([(0, "#2A2E35", 1), (1, "#181B20", 1)], 0, 0, 1, 0), 8)
    doc.rect(x + 6, y + 6, w - 12, 26, "#14171B", 4)
    for i in range(int((w - 40) // 14)):
        doc.rect(x + 20 + i * 14, y + 13, 8, 12, "#2E333A", 2)
    ix, iy, iw = x + 22, y + 44, w - 44
    doc.rect(ix - 8, iy - 4, iw + 16, h - 92, "#0D0F12", 4)
    kinds = ["switch", "switch", "server", "server", "server", "storage", "server", "storage", "server"]
    yy = iy + 4
    for k, kind in enumerate(kinds):
        uh = 34 if kind == "switch" else 52
        if yy + uh > y + h - 56:
            break
        rack_unit(doc, ix, yy, iw, uh, kind=kind, led="#8E99A6", rng_bits=k + rng.randrange(3))
        yy += uh + 6
    doc.rect(x + 14, y + h - 42, w - 28, 28, "#14171B", 4)
    for fx in (x + 18, x + w - 42):
        doc.rect(fx, y + h, 24, 10, "#0E1013", 2)
    # open glass door, seen edge-on at the left
    doc.poly([(x - 34, y + 20), (x, y), (x, y + h), (x - 34, y + h - 20)], "#9FB3C8", opacity=0.25)
    doc.path(f"M{x - 34} {y + 20}L{x} {y}V{y + h}L{x - 34} {y + h - 20}Z", stroke="#5C6B7A", sw=2)


def _cloud(doc: Doc, cx: float, base: float, w: float, accent: str) -> None:
    """A soft cloud resting on the pan."""
    h = w * 0.52
    x0 = cx - w / 2
    d = (f"M{f(x0 + w * 0.14)} {f(base)}"
         f"A{f(w * 0.15)} {f(w * 0.15)} 0 0 1 {f(x0 + w * 0.10)} {f(base - h * 0.52)}"
         f"A{f(w * 0.22)} {f(w * 0.22)} 0 0 1 {f(x0 + w * 0.42)} {f(base - h * 0.88)}"
         f"A{f(w * 0.24)} {f(w * 0.24)} 0 0 1 {f(x0 + w * 0.82)} {f(base - h * 0.62)}"
         f"A{f(w * 0.17)} {f(w * 0.17)} 0 0 1 {f(x0 + w * 0.88)} {f(base)}Z")
    doc.path(d, fill="#000", opacity=0.14, extra=f' filter="{doc.blur(10)}" transform="translate(8 14)"')
    doc.path(d, fill=doc.lin([(0, "#FFFFFF", 1), (1, "#DCE6F5", 1)]))
    doc.path(d, stroke=accent, sw=8)


def _pan(doc: Doc, cx: float, top: float, y: float, w: float, brass: str, ink: str) -> None:
    """Strings from the beam end down to a shallow pan whose rim is at y."""
    for dx in (-w * 0.46, 0.0, w * 0.46):
        doc.line((cx, top), (cx + dx, y), ink, 3, 0.8)
    doc.path(f"M{f(cx - w / 2)} {f(y)}Q{f(cx)} {f(y + 70)} {f(cx + w / 2)} {f(y)}Z", fill=brass)
    doc.add(f'<ellipse cx="{f(cx)}" cy="{f(y)}" rx="{f(w / 2)}" ry="12" fill="#8A6420"/>')


@scene("selfhosted_saas")
def selfhosted_saas(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.5, 0.15))
    ink = "#2B2620"
    brass = doc.lin([(0, "#F3D98B", 1), (0.5, "#C99A3A", 1), (1, "#8A6420", 1)], 0, 0, 1, 0.4)
    cx, beam_y, pan_y = 800.0, 150.0, 660.0
    lx, rx = 370.0, 1230.0
    # post and foot
    doc.add(f'<ellipse cx="{f(cx)}" cy="{f(858)}" rx="230" ry="20" fill="#000" opacity="0.18" '
            f'filter="{doc.blur(8)}"/>')
    doc.rect(cx - 16, beam_y, 32, 680, brass, 8)
    doc.path(f"M{f(cx - 180)} {f(860)}Q{f(cx)} {f(790)} {f(cx + 180)} {f(860)}Z", fill=brass)
    # beam
    doc.rect(lx - 10, beam_y - 14, rx - lx + 20, 28, brass, 14)
    doc.circle(cx, beam_y, 34, brass, "#8A6420", 4)
    doc.poly([(cx, beam_y - 90), (cx - 20, beam_y - 30), (cx + 20, beam_y - 30)], "#8A6420")
    for x in (lx, rx):
        doc.circle(x, beam_y, 14, "#8A6420")
    # left: the company's own cabinet
    _pan(doc, lx, beam_y, pan_y, 500, brass, ink)
    _cabinet(doc, lx - 125, pan_y - 430, 250, 426, rng)
    # right: the cloud service
    _pan(doc, rx, beam_y, pan_y, 500, brass, ink)
    _cloud(doc, rx, pan_y - 6, 480, p.accent)
    for x, label in ((lx, "SELF-HOSTED"), (rx, "SaaS")):
        doc.text(label, x, pan_y + 150, 64, p.ink, "display", anchor="middle", tracking=2)
    doc.focus = Box(70, 40, 1460, 821)
    vignette(doc, 0.3)
    _ = brief
