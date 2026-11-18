"""Espionage backdoor, taken literally: a government building at night, its
public front lit and closed, and in the side wall a small door left ajar,
light spilling out. From that door a thin channel climbs to an ordinary
cloud, which is where the sources say the backdoor gets its commands (when
they say so); otherwise the channel runs out of frame. When the sources say
mail was stolen, envelopes travel along it.

Everything is a symbol: no workstation screenshot, no process list, no file
names, no operator console, no command strings. The operation's name appears
as plain text only when the headline names it."""
from __future__ import annotations

import random

from .. import type as T
from ..brief import EditorialBrief, mentions
from ..kit import Box, Doc, W, H, f
from . import scene

_ATTACK = ("exploited", "confirmed", "attacks_observed", "compromise")


def _cloud(doc: Doc, cx: float, cy: float, s: float, fill: str) -> None:
    doc.path(f"M{f(cx - s)} {f(cy + 0.3 * s)}A{f(0.3 * s)} {f(0.3 * s)} 0 0 1 {f(cx - 0.75 * s)} {f(cy - 0.12 * s)}"
             f"A{f(0.38 * s)} {f(0.38 * s)} 0 0 1 {f(cx - 0.12 * s)} {f(cy - 0.36 * s)}"
             f"A{f(0.42 * s)} {f(0.42 * s)} 0 0 1 {f(cx + 0.62 * s)} {f(cy - 0.06 * s)}"
             f"A{f(0.28 * s)} {f(0.28 * s)} 0 0 1 {f(cx + s)} {f(cy + 0.3 * s)}Z", fill=fill)


def _envelope(doc: Doc, cx: float, cy: float, w: float, color: str, rot: float) -> None:
    h = w * 0.66
    with doc.g(transform=f"rotate({f(rot)} {f(cx)} {f(cy)})"):
        doc.rect(cx - w / 2, cy - h / 2, w, h, color, 3)
        doc.path(f"M{f(cx - w / 2)} {f(cy - h / 2)}L{f(cx)} {f(cy + h * 0.1)}L{f(cx + w / 2)} {f(cy - h / 2)}",
                 stroke="#3A1A12", sw=2)


def _building(doc: Doc, ink: str) -> tuple[float, float, float, float]:
    """A classical government building in three-quarter view: pediment and
    columns on the front face, a plain side wall receding to the right.
    Returns the side wall's (x0, x1, top-at-x, base) helper values for the door."""
    stone, stone_dk, shade = "#C9D3E3", "#8D9AB0", "#56627A"
    gx = 840.0                        # the front/side corner
    fx0 = 150.0                       # front face left edge
    top, base = 330.0, 760.0          # entablature top and ground at the corner
    sx1, s_top, s_base = 1240.0, 380.0, 700.0   # far end of the side wall
    # ground shadow
    doc.add(f'<ellipse cx="{f((fx0 + sx1) / 2)}" cy="{f(base + 20)}" rx="{f((sx1 - fx0) * 0.62)}" ry="40" '
            f'fill="#000" opacity="0.5" filter="{doc.blur(18)}"/>')
    # side wall (in shade) and its roof
    doc.poly([(gx, top), (sx1, s_top), (sx1, s_base), (gx, base)], doc.lin([(0, shade, 1), (1, "#323A4C", 1)],
                                                                           0, 0, 1, 0))
    apex = ((fx0 + gx) / 2, top - 150)
    back = (apex[0] + (sx1 - gx) * 0.92, apex[1] + (s_top - top) * 1.5 + 20)
    doc.poly([apex, (gx + 20, top), (sx1 + 12, s_top), back], doc.lin([(0, "#4A556C", 1), (1, "#2C3446", 1)],
                                                                       0, 0, 1, 1))
    # cornice line along the side
    doc.line((gx, top + 24), (sx1, s_top + 14), "#6A7690", 3)
    # front face: steps, columns, entablature, pediment
    for i in range(3):
        doc.rect(fx0 - 30 + i * 14, base - 26 * (i + 1) + 26, gx - fx0 + 60 - i * 28, 26,
                 stone if i == 2 else stone_dk)
    doc.rect(fx0, top, gx - fx0, 64, stone)
    doc.rect(fx0, top + 64, gx - fx0, 10, stone_dk)
    doc.poly([(fx0 - 20, top), ((fx0 + gx) / 2, top - 150), (gx + 20, top)], stone)
    doc.poly([(fx0 + 40, top - 14), ((fx0 + gx) / 2, top - 122), (gx - 40, top - 14)], "#AEB9CC")
    n = 6
    span = (gx - fx0 - 60) / (n - 1)
    doc.rect(fx0, top + 74, gx - fx0, base - 78 - top - 74, "#2A3142")   # the dark portico behind columns
    for i in range(n):
        cx = fx0 + 30 + i * span
        doc.rect(cx - 24, top + 80, 48, base - 78 - top - 84, doc.lin([(0, "#E2E8F2", 1), (0.6, stone, 1),
                                                                      (1, stone_dk, 1)], 0, 0, 1, 0))
        doc.rect(cx - 32, top + 74, 64, 14, stone)
        doc.rect(cx - 32, base - 92, 64, 14, stone)
    # front doors: shut
    doc.rect((fx0 + gx) / 2 - 46, base - 250, 92, 172, "#1C2232")
    doc.line(((fx0 + gx) / 2, base - 250), ((fx0 + gx) / 2, base - 78), "#3A4458", 2)
    return gx, sx1, top, base


@scene("espionage_backdoor")
def espionage_backdoor(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    red = p.danger
    cloud = any(k in text for k in ("cloud", "хмар", "onedrive", "dropbox", "google drive", "graph api"))
    mail = any(k in text for k in ("email", "mail", "exchange", "пошт", "лист"))
    active = brief.status in _ATTACK

    # night: deep blue sky, moonlight from the upper left
    doc.rect(0, 0, W, H, doc.lin([(0, "#0B1424", 1), (0.75, "#121D33", 1), (1, "#070B14", 1)]))
    doc.rect(0, 0, W, H, doc.rad([(0, "#8FB0E6", 0.20), (1, "#8FB0E6", 0)], 0.18, 0.12, 0.5))
    doc.rect(0, 760, W, H - 760, doc.lin([(0, "#0A0F1A", 1), (1, "#05070C", 1)]))

    gx, sx1, top, base = _building(doc, p.ink)

    # the back door in the side wall: ajar, light spilling onto the ground
    t = 0.55                                       # position along the side wall
    dx = gx + (sx1 - gx) * t
    s_top, s_base = 380.0, 700.0
    wall_b = base + (s_base - base) * t
    dh, dw = 150.0, 70.0
    slope = (s_base - base) / (sx1 - gx)
    d0 = (dx, wall_b)
    d1 = (dx + dw, wall_b + slope * dw)
    door = [(d0[0], d0[1] - dh), (d1[0], d1[1] - dh * 0.96), d1, d0]
    glow = red if active else "#F5B83D"
    doc.poly([d0, d1, (d1[0] + 160, d1[1] + 70), (d0[0] - 40, d0[1] + 90)], glow, opacity=0.28)
    doc.glow(dx + dw / 2, wall_b - dh / 2, 120, 130, glow, 0.35)
    doc.poly(door, glow)
    # the door leaf, swung open towards the viewer
    doc.poly([(d0[0], d0[1] - dh), (d0[0] - 46, d0[1] - dh + 20), (d0[0] - 46, d0[1] + 14), d0], "#1A2030",
             stroke="#3A4458", sw=1.5)

    # the channel: from the door up to the cloud (or out of frame)
    start = (dx + dw / 2, wall_b - dh - 10)
    end = (1330.0, 300.0) if cloud else (W + 20, 120.0)
    c1 = (start[0] + 40, start[1] - 180)
    path = f"M{f(start[0])} {f(start[1])}Q{f(c1[0])} {f(c1[1])} {f(end[0])} {f(end[1])}"
    doc.path(path, stroke=glow, sw=7, dash="2 16", opacity=0.95)
    if mail:
        for k, u in enumerate((0.35, 0.62)):
            x = (1 - u) ** 2 * start[0] + 2 * (1 - u) * u * c1[0] + u * u * end[0]
            y = (1 - u) ** 2 * start[1] + 2 * (1 - u) * u * c1[1] + u * u * end[1]
            _envelope(doc, x, y, 64 - k * 10, "#F2E3C9", -18 + k * 10)
    if cloud:
        doc.glow(1360, 210, 230, 110, "#9FB4D8", 0.18)
        _cloud(doc, 1360, 220, 210, doc.lin([(0, "#E6ECF5", 1), (1, "#A9B7CC", 1)]))

    # the operation name, when the headline gives one
    head = text[:120]
    name = next((e for e in brief.entities if mentions(e, head) and T.supported(e, "display") == e
                 and any(ch.isupper() for ch in e[1:])), "")
    if name:
        doc.text(name, 150, 140, 72, p.ink, "display", opacity=0.92)

    doc.rect(0, 0, W, H, doc.rad([(0.6, "#000", 0), (1, "#000", 0.5)], 0.5, 0.5, 0.78))
    doc.focus = Box(110, 40, 1460, 821)
