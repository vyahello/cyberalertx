"""Telecom networks: a mobile mast as a large silhouette against a dusk sky,
its sector antennas sending radio arcs over a city skyline.

Analysis or conference coverage (no incident): the mast stands calm, arcs in
the accent colour. Only when the sources report attacks that intercept
messages (calls / SMS) is a text bubble drawn in the danger colour, its
content masked (no code or number is invented), with a ghost copy peeled off
it toward an eye: the message read in transit. No network architecture
(backhaul, backup power, routes) is drawn, because the sources do not
describe one."""
from __future__ import annotations

import math
import random

from ..brief import EditorialBrief
from ..kit import H, W, Box, Doc, f
from . import scene

_GROUND = 790.0


def _mast(doc: Doc, cx: float, top: float, ink: str, rim: str) -> list[tuple[float, float]]:
    """Tapered lattice mast in silhouette. Returns the antenna face centres."""
    base_w, top_w = 210.0, 54.0

    def leg(y: float) -> tuple[float, float]:
        t = (y - top) / (_GROUND - top)
        hw = (top_w + (base_w - top_w) * t) / 2
        return cx - hw, cx + hw

    lt, rt = leg(top)
    lb, rb = leg(_GROUND)
    doc.path(f"M{f(lt)} {f(top)}L{f(lb)} {f(_GROUND)}M{f(rt)} {f(top)}L{f(rb)} {f(_GROUND)}", stroke=ink, sw=9)
    doc.path(f"M{f(rt + 3)} {f(top)}L{f(rb + 3)} {f(_GROUND)}", stroke=rim, sw=2, opacity=0.55)
    d = []
    ys = []
    y = top
    step = 60.0
    while y < _GROUND - 1:
        ys.append(y)
        y += step
        step *= 1.08
    ys.append(_GROUND)
    for a, b in zip(ys, ys[1:]):
        la, ra = leg(a)
        lb_, rb_ = leg(b)
        d.append(f"M{f(la)} {f(a)}H{f(ra)}")
        d.append(f"M{f(la)} {f(a)}L{f(rb_)} {f(b)}M{f(ra)} {f(a)}L{f(lb_)} {f(b)}")
    doc.path("".join(d), stroke=ink, sw=4)
    # lightning rod + aviation light
    doc.line((cx, top), (cx, top - 80), ink, 4)
    doc.glow(cx, top - 84, 26, 26, "#FF8A65", 0.6)
    doc.circle(cx, top - 84, 7, "#FFB199")
    # headframe and three sector antennas (centre face-on, sides edge-on)
    hy = top + 30
    doc.rect(cx - 140, hy - 4, 280, 9, ink, 3)
    doc.rect(cx - 140, hy + 150, 280, 9, ink, 3)
    faces = []
    for px, pw in ((cx - 132, 30), (cx - 34, 68), (cx + 102, 30)):
        doc.rect(px, hy - 22, pw, 190, ink, 9)
        doc.rect(px + pw - 3, hy - 18, 2, 182, rim, 1, opacity=0.45)
        faces.append((px + pw / 2, hy + 70))
    # radio units
    for rx in (cx - 92, cx + 56):
        doc.rect(rx, hy + 190, 38, 66, ink, 4)
    # a microwave dish on the right leg
    my = top + 360
    _, r_leg = leg(my)
    doc.line((r_leg, my), (r_leg + 30, my), ink, 6)
    doc.add(f'<ellipse cx="{f(r_leg + 44)}" cy="{f(my)}" rx="20" ry="58" fill="{ink}"/>')
    doc.add(f'<ellipse cx="{f(r_leg + 48)}" cy="{f(my)}" rx="5" ry="50" fill="{rim}" opacity="0.4"/>')
    # foundation
    doc.rect(lb - 30, _GROUND - 6, rb - lb + 60, 20, ink, 2)
    return faces


def _skyline(doc: Doc, rng: random.Random, ink: str, glow: str) -> None:
    x = -20.0
    d = ""
    wins = ""
    while x < W:
        w = rng.uniform(60, 150)
        h = rng.uniform(40, 190)
        d += f"M{f(x)} {f(_GROUND)}V{f(_GROUND - h)}H{f(x + w)}V{f(_GROUND)}Z"
        for _ in range(int(h * w / 2600)):
            wx, wy = rng.uniform(x + 8, x + w - 14), rng.uniform(_GROUND - h + 10, _GROUND - 14)
            wins += f"M{f(wx)} {f(wy)}h6v8h-6Z"
        x += w + rng.uniform(2, 18)
    doc.path(d, fill=ink)
    doc.path(wins, fill=glow, opacity=0.55)


def _arcs(doc: Doc, cx: float, cy: float, color: str, side: int, n: int = 4, r0: float = 60,
          step: float = 52) -> None:
    for k in range(n):
        r = r0 + k * step
        a = math.radians(32)
        x0, y0 = cx + side * r * math.cos(a), cy - r * math.sin(a)
        x1, y1 = cx + side * r * math.cos(a), cy + r * math.sin(a)
        doc.path(f"M{f(x0)} {f(y0)}A{f(r)} {f(r)} 0 0 {1 if side > 0 else 0} {f(x1)} {f(y1)}", stroke=color,
                 sw=7 - k, opacity=0.95 - k * 0.18)


def _bubble(doc: Doc, b: Box, fill: str, ink: str, *, stroke: str = "", dots: str = "",
            opacity: float = 1.0) -> None:
    with doc.g(opacity=opacity):
        doc.path(f"M{f(b.x + 30)} {f(b.y)}H{f(b.r - 30)}Q{f(b.r)} {f(b.y)} {f(b.r)} {f(b.y + 30)}"
                 f"V{f(b.b - 30)}Q{f(b.r)} {f(b.b)} {f(b.r - 30)} {f(b.b)}H{f(b.x + 70)}L{f(b.x + 20)} "
                 f"{f(b.b + 40)}L{f(b.x + 34)} {f(b.b - 2)}Q{f(b.x)} {f(b.b - 6)} {f(b.x)} {f(b.b - 34)}"
                 f"V{f(b.y + 30)}Q{f(b.x)} {f(b.y)} {f(b.x + 30)} {f(b.y)}Z", fill=fill,
                 stroke=stroke, sw=4 if stroke else 1)
        # masked content: no code is shown, only that one is there
        n = 6
        for k in range(n):
            doc.circle(b.x + 56 + k * (b.w - 112) / (n - 1), b.cy, 15, dots or ink)


@scene("telecom")
def telecom(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    intercept = brief.status in ("exploited", "attacks_observed", "confirmed") and \
        any(w in brief.text for w in ("sms", "intercept", "texts", "calls"))
    # dusk sky: deep blue above, a warm band on the horizon
    doc.rect(0, 0, W, H, doc.lin([(0, "#070B14", 1), (0.55, "#1A2C4D", 1), (0.86, "#B5664A", 1),
                                  (1, "#E59A5C", 1)]))
    doc.rect(0, 0, W, H, doc.rad([(0, "#FFC58A", 0.35), (1, "#FFC58A", 0)], 0.36, 0.95, 0.5))
    ink = "#060912"
    rim = "#FFB98A"
    _skyline(doc, rng, "#0B1222", "#FFC58A")
    mx = 470.0 if intercept else 560.0
    faces = _mast(doc, mx, 150, ink, rim)
    doc.rect(0, _GROUND, W, H - _GROUND, ink)
    col = p.danger if intercept else p.accent
    _arcs(doc, faces[0][0] - 20, faces[0][1], p.accent, -1, r0=70)
    _arcs(doc, faces[2][0] + 20, faces[2][1], col if intercept else p.accent, 1, n=5, r0=80, step=60)
    if intercept:
        msg = Box(860, 170, 440, 150)
        doc.shadow(msg.x, msg.y, msg.w, msg.h, 30, 0.8)
        _bubble(doc, msg, "#F4F7FB", "#1A2438")
        # the ghost copy peeled off in transit, toward the watcher
        ghost = Box(960, 440, 440, 150)
        doc.path(f"M{f(msg.cx)} {f(msg.b + 10)}C{f(msg.cx)} {f(msg.b + 70)} {f(ghost.cx - 60)} "
                 f"{f(ghost.y - 70)} {f(ghost.cx - 40)} {f(ghost.y - 8)}", stroke=p.danger, sw=4, dash="10 9")
        _bubble(doc, ghost, p.danger, "#FFFFFF", opacity=0.92, dots="#FFFFFF")
        # the eye: read in transit
        ex, ey = 1500, 515
        doc.path(f"M{f(ghost.r + 6)} {f(ghost.cy)}H{f(ex - 96)}", stroke=p.danger, sw=4, dash="10 9")
        eye = (f"M{f(ex - 84)} {f(ey)}Q{f(ex)} {f(ey - 76)} {f(ex + 84)} {f(ey)}Q{f(ex)} {f(ey + 76)} "
               f"{f(ex - 84)} {f(ey)}Z")
        doc.path(eye, fill="#0B1222", stroke=p.danger, sw=8)
        doc.circle(ex, ey, 26, p.danger)
        doc.circle(ex - 8, ey - 8, 7, "#FFFFFF", opacity=0.8)
        name = next((e for e in brief.entities if e.lower() == "silentair"), "")
        if name:
            doc.text(name, 80, 866, 50, "#E8EDF5", "display")
        doc.focus = Box(300, 40, 1300, 731)
    else:
        doc.focus = Box(160, 40, 1060, 596)
    doc.rect(0, 0, W, H, doc.rad([(0.55, "#000", 0), (1, "#000", 0.45)], 0.45, 0.45, 0.8))
