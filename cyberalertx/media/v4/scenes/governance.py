"""Cyber risk as a management topic (analysis, no incident): a boardroom
table seen from above, chairs around it, and three cards laid out on it,
one per question such columns put to the leadership: what is critical
(systems and data), how an incident would be detected, how fast the business
recovers. Each card carries a pictogram and a question mark.

This is an editorial device, visibly conceptual: no risk matrix, no RACI
roles, no invented policy text or figures."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, icon, vignette
from . import scene


def _chair(doc: Doc, cx: float, cy: float, rot: float) -> None:
    with doc.g(f"translate({f(cx)} {f(cy)}) rotate({f(rot)})"):
        doc.rect(-58 + 6, -46 + 14, 116, 104, "#000", 26, opacity=0.18, extra=f' filter="{doc.blur(8)}"')
        doc.rect(-58, -46, 116, 100, doc.lin([(0, "#3C3F46", 1), (1, "#22242A", 1)]), 26)
        doc.rect(-66, 30, 132, 30, doc.lin([(0, "#2C2F35", 1), (1, "#18191D", 1)]), 14)
        doc.rect(-40, -34, 80, 40, "#FFFFFF", 16, opacity=0.06)


def _card(doc: Doc, cx: float, cy: float, rot: float, kind: str, ink: str, accent: str) -> None:
    w, h = 300.0, 360.0
    with doc.g(f"rotate({f(rot)} {f(cx)} {f(cy)})"):
        doc.rect(cx - w / 2 + 10, cy - h / 2 + 18, w, h, "#000", 10, opacity=0.35, extra=f' filter="{doc.blur(12)}"')
        doc.rect(cx - w / 2, cy - h / 2, w, h, "#FBF8F2", 8)
        doc.rect(cx - w / 2, cy - h / 2, w, 12, accent, 8)
        doc.rect(cx - w / 2, cy - h / 2 + 6, w, 6, accent)
        iy = cy - 20
        if kind == "data":
            # critical systems and data: a stacked database
            top, rx, ry = iy - 86, 82.0, 26.0
            doc.add(f'<ellipse cx="{f(cx)}" cy="{f(top)}" rx="{f(rx)}" ry="{f(ry)}" fill="none" stroke="{ink}" '
                    f'stroke-width="11"/>')
            d = f"M{f(cx - rx)} {f(top)}V{f(top + 132)}M{f(cx + rx)} {f(top)}V{f(top + 132)}"
            for k in (1, 2, 3):
                y = top + k * 44
                d += f"M{f(cx - rx)} {f(y)}A{f(rx)} {f(ry)} 0 0 0 {f(cx + rx)} {f(y)}"
            doc.path(d, stroke=ink, sw=11)
        elif kind == "detect":
            doc.path(f"M{f(cx - 100)} {f(iy)}Q{f(cx)} {f(iy - 96)} {f(cx + 100)} {f(iy)}Q{f(cx)} {f(iy + 96)} "
                     f"{f(cx - 100)} {f(iy)}Z", stroke=ink, sw=11)
            doc.circle(cx, iy, 30, ink)
        else:
            icon(doc, "clock", cx, iy, 190, ink, 11)
        doc.text("?", cx, cy + h / 2 - 34, 84, accent, "display", anchor="middle")


@scene("governance")
def governance(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.5, 0.2))
    # carpet texture under the table
    doc.rect(0, 0, 1600, 900, doc.rad([(0, "#FFFFFF", 0.25), (1, "#000", 0.08)], 0.5, 0.45, 0.7))
    t = Box(150, 190, 1300, 520)
    for k in range(5):           # chairs along both long sides
        x = t.x + 170 + k * 240
        _chair(doc, x, t.y - 36, 180)
        _chair(doc, x, t.b + 36, 0)
    _chair(doc, t.x - 40, t.cy, 90)
    _chair(doc, t.r + 40, t.cy, -90)
    # the table: walnut top with a soft reflection
    doc.rect(t.x + 16, t.y + 40, t.w, t.h, "#000", t.h / 2, opacity=0.35, extra=f' filter="{doc.blur(26)}"')
    doc.rect(t.x, t.y, t.w, t.h, doc.lin([(0, "#6B4A33", 1), (0.5, "#553826", 1), (1, "#3E281B", 1)], 0, 0, 1, 1),
             t.h / 2)
    grain = "".join(f"M{f(t.x + 120)} {f(t.y + 40 + k * 22 + rng.uniform(-4, 4))}"
                    f"C{f(t.x + 500)} {f(t.y + 30 + k * 22)} {f(t.x + 800)} {f(t.y + 52 + k * 22)} "
                    f"{f(t.r - 120)} {f(t.y + 40 + k * 22)}" for k in range(21))
    with doc.g(clip=doc.clip_rect(t.x, t.y, t.w, t.h, t.h / 2)):
        doc.path(grain, stroke="#2E1E14", sw=2, opacity=0.25)
        doc.rect(t.x, t.y, t.w, 120, doc.lin([(0, "#FFFFFF", 0.16), (1, "#FFFFFF", 0)]))
    # the three questions
    ink = "#1B1D22"
    _card(doc, 470, t.cy + 4, -4, "data", ink, p.accent)
    _card(doc, 800, t.cy - 6, 2, "detect", ink, p.accent)
    _card(doc, 1130, t.cy + 6, -2, "recover", ink, p.accent)
    doc.focus = Box(250, 150, 1100, 619)
    vignette(doc, 0.3)
    _ = brief
