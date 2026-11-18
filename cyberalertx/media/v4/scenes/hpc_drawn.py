"""Supercomputer machine hall, drawn (used by `hpc_hall` when no verified
library photograph of the named system exists).

One-point perspective down the cold aisle: two rows of dense HPC cabinets
with glass doors, node chassis and status LEDs, a raised-tile floor that
reflects them, cable trays and light lines overhead. The compromise is
restrained: one cabinet pair (the login nodes users connect to) is bracketed,
and the account figure appears only when the sources state it."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from ..kit import H, W, Box, Doc, f, icon
from . import scene

# camera: eye height (m), focal length (px), vanishing point
_EYE, _FL, _VX, _VY = 1.62, 900.0, 800.0, 360.0
_AISLE = 1.45            # half-width of the cold aisle (m)
_DEPTH = 1.2             # cabinet depth (m)
_RACK_H = 2.25           # cabinet height (m)
_CAB = 0.62              # cabinet width along the aisle (m)
_Z0, _Z1 = 3.1, 46.0    # first / last cabinet face


def _P(x: float, y: float, z: float) -> tuple[float, float]:
    """World (x right, y up, z forward) -> screen."""
    return _VX + _FL * x / z, _VY + _FL * (_EYE - y) / z


def _quad(pts: list[tuple[float, float]]) -> str:
    return "M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts) + "Z"


def _cabinet_zs() -> list[float]:
    zs, z = [], _Z0
    while z < _Z1:
        zs.append(z)
        z += _CAB
    return zs


def _row(doc: Doc, side: int, *, hot: set[int], reflect: bool, rng: random.Random, danger: str) -> None:
    """One row of cabinets facing the aisle. side=-1 left, +1 right."""
    x = side * _AISLE
    ysign = -1 if reflect else 1
    zs = _cabinet_zs()
    # Draw far to near so near cabinets overlap correctly.
    frames, doors, seams, chassis, leds_g, leds_b, leds_r = [], [], [], [], [], [], []
    hot_doors: list[str] = []
    handles: list[str] = []
    for i in reversed(range(len(zs))):
        za, zb = zs[i], zs[i] + _CAB
        ya, yb = 0.0, _RACK_H * ysign
        a, b, c, d = _P(x, ya, za), _P(x, yb, za), _P(x, yb, zb), _P(x, ya, zb)
        frames.append(_quad([a, b, c, d]))
        # door glass inset (frame ~4 cm)
        m = 0.045
        ia, ib = _P(x, (0.12) * ysign, za + m), _P(x, (_RACK_H - 0.06) * ysign, za + m)
        ic, id_ = _P(x, (_RACK_H - 0.06) * ysign, zb - m), _P(x, 0.12 * ysign, zb - m)
        doors.append(_quad([ia, ib, ic, id_]))
        if i in hot:
            hot_doors.append(_quad([ia, ib, ic, id_]))
        # door handle near the far edge
        if za < 14:
            h0, h1 = _P(x, 1.0 * ysign, zb - 0.09), _P(x, 1.35 * ysign, zb - 0.09)
            handles.append(f"M{f(h0[0])} {f(h0[1])}L{f(h1[0])} {f(h1[1])}")
        seams.append(f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}")
        # node chassis: 18 slots, lines across the door
        if za < 26:
            for k in range(1, 18):
                yy = (0.12 + k * (_RACK_H - 0.18) / 18) * ysign
                p0, p1 = _P(x, yy, za + m), _P(x, yy, zb - m)
                chassis.append(f"M{f(p0[0])} {f(p0[1])}L{f(p1[0])} {f(p1[1])}")
        # status LEDs: a column near the hinge edge and a sparse one mid-door
        if za < 30:
            s = max(0.9, 7.5 / za)
            for k in range(18):
                yy = (0.12 + (k + 0.5) * (_RACK_H - 0.18) / 18) * ysign
                for frac, prob in ((0.16, 0.95), (0.55, 0.45), (0.8, 0.25)):
                    if rng.random() > prob:
                        continue
                    px, py = _P(x, yy, za + m + frac * (_CAB - 2 * m))
                    w = s * (1.4 if frac == 0.16 else 1.0)
                    rect = f"M{f(px - w)} {f(py - s * 0.45)}h{f(2 * w)}v{f(s * 0.9)}h{f(-2 * w)}Z"
                    if i in hot and rng.random() < 0.7:
                        leds_r.append(rect)
                    elif rng.random() < 0.18:
                        leds_b.append(rect)
                    else:
                        leds_g.append(rect)
    body = doc.lin([(0, "#0B1220", 1), (1, "#141E30", 1)], 0, 0, 0, 1)
    doc.path("".join(frames), fill="#1A2436", stroke="#2E3B52", sw=1)
    doc.path("".join(doors), fill=body)
    doc.path("".join(chassis), stroke="#24324A", sw=1)
    if hot_doors:
        doc.path("".join(hot_doors), fill=danger, opacity=0.13)
    doc.path("".join(seams), stroke="#56657E", sw=1.4, opacity=0.8)
    doc.path("".join(handles), stroke="#8C9BB4", sw=2.2, opacity=0.7)
    # top cap of the row: a lit cable-entry band above the doors
    ca, cb = _P(x, _RACK_H * ysign, _Z0), _P(x, (_RACK_H + 0.14) * ysign, _Z0)
    cc, cd = _P(x, (_RACK_H + 0.14) * ysign, _Z1), _P(x, _RACK_H * ysign, _Z1)
    doc.path(_quad([ca, cb, cc, cd]), fill="#2A374D")
    doc.line(ca, cd, "#7F93B3", 1.2, 0.7)
    doc.path("".join(leds_g), fill="#4FD1B8", opacity=0.9)
    doc.path("".join(leds_b), fill="#7DB3FF", opacity=0.85)
    if leds_r:
        doc.path("".join(leds_r), fill=danger)

    # Near end panel facing the camera (closes the row; off-canvas on the outside)
    xi, xo = x, x + side * 3.0      # back-to-back double row
    q = [_P(xi, 0, _Z0), _P(xi, _RACK_H * ysign, _Z0), _P(xo, _RACK_H * ysign, _Z0), _P(xo, 0, _Z0)]
    doc.path(_quad(q), fill=doc.lin([(0, "#22324C", 1), (0.6, "#172338", 1), (1, "#0D1524", 1)],
                                    0, 0, 0, 1 if not reflect else 0))
    # sheen from the aisle lights, strongest at the aisle edge
    doc.path(_quad(q), fill=doc.lin([(0, "#BFD6FF", 0.16), (0.35, "#BFD6FF", 0.03), (1, "#BFD6FF", 0.0)],
                                    0 if side < 0 else 1, 0, 1 if side < 0 else 0, 0))
    if not reflect:
        # panel joints and a kick plate: the end of a double row of cabinets
        joints = []
        for k in (1, 2, 3, 4):
            jx = x + side * k * 0.6
            a, b = _P(jx, 0.1, _Z0), _P(jx, _RACK_H, _Z0)
            joints.append(f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}")
        doc.path("".join(joints), stroke="#000", sw=2, opacity=0.35)
        ka, kb = _P(xi, 0.1, _Z0), _P(xo, 0.1, _Z0)
        doc.rect(min(ka[0], kb[0]), ka[1], abs(kb[0] - ka[0]), q[0][1] - ka[1], "#070B12", opacity=0.8)
        # small engraved row label (not a brand): row and cabinet range
        lx, ly = _P(xi + side * 0.3, 1.95, _Z0)
        doc.text("ROW " + ("B" if side < 0 else "C"), lx, ly, 22, "#9FB2CF", "mono_bold",
                 anchor="end" if side < 0 else "start", opacity=0.75)
    doc.line(q[0], q[1], "#8FA6C8", 1.5, 0.6)


def _floor(doc: Doc) -> None:
    """Raised-floor tiles (0.6 m) in the aisle and under the rows."""
    top = _P(0, 0, _Z1)[1]
    doc.rect(0, top, W, H - top, doc.lin([(0, "#1A2232", 1), (1, "#0E1420", 1)]))
    d = []
    for k in range(-12, 13):
        xx = k * 0.6
        a, b = _P(xx, 0, 1.2), _P(xx, 0, _Z1)
        d.append(f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}")
    z = 1.2
    while z < _Z1:
        a, b = _P(-8, 0, z), _P(8, 0, z)
        d.append(f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}")
        z += 0.6
    doc.path("".join(d), stroke="#4A5872", sw=1.2, opacity=0.7)
    # perforated tiles in the cold aisle (every other one)
    z = 2.4
    while z < 20:
        a, b, c, e = _P(-0.55, 0, z + 0.05), _P(0.55, 0, z + 0.05), _P(0.55, 0, z + 0.55), _P(-0.55, 0, z + 0.55)
        doc.path(_quad([a, b, c, e]), fill="#000", opacity=0.22)
        z += 1.8


def _ceiling(doc: Doc) -> None:
    yc = 3.4
    bot = _P(0, yc, _Z1)[1]
    doc.rect(0, 0, W, bot, doc.lin([(0, "#05080F", 1), (1, "#0D1422", 1)]))
    # light lines along the aisle
    for xx in (-0.5, 0.5):
        a, b = _P(xx, yc - 0.02, 1.0), _P(xx, yc - 0.02, _Z1)
        doc.path(f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}", stroke="#CFE3FF", sw=5, opacity=0.18,
                 extra=f' filter="{doc.blur(4)}"')
        doc.path(f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}", stroke="#E6F0FF", sw=2.2, opacity=0.75)
    # cable trays above each row
    for side in (-1, 1):
        x0, x1 = side * (_AISLE + 0.15), side * (_AISLE + 0.85)
        y = _RACK_H + 0.35
        q = [_P(x0, y, 1.0), _P(x1, y, 1.0), _P(x1, y, _Z1), _P(x0, y, _Z1)]
        doc.path(_quad(q), fill="#1C2433")
        rail = [_P(x0, y, 1.0), _P(x0, y, _Z1)]
        doc.line(rail[0], rail[1], "#4B5870", 2)
        rungs = []
        z = 1.2
        while z < 30:
            a, b = _P(x0, y, z), _P(x1, y, z)
            rungs.append(f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}")
            z += 0.5
        doc.path("".join(rungs), stroke="#3A4659", sw=1.2)


def _bracket(doc: Doc, x0: float, y0: float, x1: float, y1: float, color: str, arm: float = 28) -> None:
    for (cx, cy, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        doc.path(f"M{f(cx)} {f(cy + dy * arm)}V{f(cy)}H{f(cx + dx * arm)}", stroke=color, sw=4, cap="square",
                 join="miter")


def _accounts(doc: Doc, x: float, y: float, brief: EditorialBrief) -> tuple[float, float]:
    p = doc.pal
    n = brief.facts.get("accounts")
    label = (f"{n}+" if brief.facts.get("accounts_plus") else str(n))
    w, h = 470, 150
    doc.rect(x + 8, y + 18, w, h, "#000", 14, opacity=0.4, extra=f' filter="{doc.blur(16)}"')
    doc.rect(x, y, w, h, "#0A111C", 14, opacity=0.94)
    doc.rect(x, y, w, h, "none", 14, stroke="#FFFFFF", sw=1, opacity=0.14)
    icon(doc, "user", x + 44, y + 56, 38, p.danger, 2.6)
    doc.text(label, x + 78, y + 76, 56, "#FFFFFF", "display")
    cols = 11
    for r in range(2):
        for c in range(cols):
            hit = (r * cols + c) % 6 != 4
            doc.rect(x + 30 + c * 38.5, y + 100 + r * 22, 30, 14, p.danger if hit else "#2B3A50", 4)
    return x, y + h


@scene("hpc_drawn")
def hpc_drawn(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    doc.rect(0, 0, W, H, "#0A0F1A")
    _ceiling(doc)
    _floor(doc)

    compromised = brief.status in ("compromise", "exploited", "confirmed", "attacks_observed")
    zs = _cabinet_zs()
    hot_i = {3, 4} if compromised else set()      # login-node pair on the right row, mid-depth

    # reflections first (glossy floor), then a floor wash to fade them
    for side in (-1, 1):
        _row(doc, side, hot=hot_i if side > 0 else set(), reflect=True, rng=random.Random(rng.random()),
             danger=p.danger)
    top = _P(0, 0, _Z1)[1]
    doc.rect(0, top, W, H - top, doc.lin([(0, "#121A28", 0.55), (0.25, "#121A28", 0.78), (1, "#0B111C", 0.93)]))
    # haze down the aisle
    doc.glow(_VX, _VY, 260, 120, "#9CC2FF", 0.16)
    for side in (-1, 1):
        _row(doc, side, hot=hot_i if side > 0 else set(), reflect=False, rng=random.Random(rng.random()),
             danger=p.danger)

    if compromised:
        za, zb = zs[min(hot_i)], zs[max(hot_i)] + _CAB
        a, b = _P(_AISLE, _RACK_H, za), _P(_AISLE, 0, za)
        c, d = _P(_AISLE, _RACK_H, zb), _P(_AISLE, 0, zb)
        x0, x1 = min(a[0], c[0]) - 16, max(a[0], c[0]) + 16
        y0, y1 = min(a[1], c[1]) - 16, max(b[1], d[1]) + 16
        doc.glow((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * 0.6, (y1 - y0) * 0.5, p.danger, 0.10)
        _bracket(doc, x0, y0, x1, y1, p.danger)
        if brief.facts.get("accounts"):
            px = (x0 + x1) / 2 - 90
            _accounts(doc, px, 40, brief)
            doc.path(f"M{f((x0 + x1) / 2)} {f(y0 - 6)}V190", stroke=p.danger, sw=2.5, dash="6 6")
            doc.circle((x0 + x1) / 2, 190, 5, p.danger)

    doc.focus = Box(440, 20, 1040, 585)
    # depth: darken the frame edges
    doc.rect(0, 0, W, H, doc.rad([(0.5, "#000", 0), (1, "#000", 0.55)], 0.51, 0.42, 0.78))
