"""Remote crash (denial of service) as one physical image: a server tower
knocked off balance by a noisy signal arriving over the network. The
headline's claim is exactly that (crafted traffic crashes the server); the
picture adds nothing technical to it.

No console, no kernel trace, no packet header, no hostname, no interface
name. The flaw's name (or a CVE from `brief.facts`) appears as plain text;
the affected services appear as small labels only when the sources list them."""
from __future__ import annotations

import math
import random

from .. import type as T
from ..brief import EditorialBrief, mentions
from ..kit import Box, Doc, W, H, f
from . import scene

_ATTACK = ("exploited", "confirmed", "attacks_observed", "compromise")
_SERVICES = ("nginx", "apache", "ssh", "mongodb", "redis", "postgresql", "mysql")


def _tower(doc: Doc, x: float, y: float, w: float, h: float, red: str, hit_y: float) -> None:
    """A tower server in oblique view, drawn upright at (x, y, w, h)."""
    dx, dy = 120.0, 70.0
    doc.poly([(x, y), (x + dx, y - dy), (x + w + dx, y - dy), (x + w, y)], doc.lin([(0, "#55607A", 1),
                                                                                   (1, "#3A4459", 1)], 0, 0, 1, 0))
    doc.poly([(x + w, y), (x + w + dx, y - dy), (x + w + dx, y + h - dy), (x + w, y + h)],
             doc.lin([(0, "#20283A", 1), (1, "#141A27", 1)]))
    doc.rect(x, y, w, h, doc.lin([(0, "#56627C", 1), (1, "#2E374B", 1)], 0, 0, 1, 1))
    doc.rect(x, y, w, 4, "#FFFFFF", opacity=0.2)
    # drive bays
    for i in range(4):
        by = y + 40 + i * 58
        doc.rect(x + 28, by, w - 56, 44, "#1A2030", 4, stroke="#4E5A72", sw=1.2)
        doc.rect(x + 44, by + 18, w - 120, 8, "#3A4458", 3)
    # vent
    for i in range(9):
        doc.rect(x + 28, y + 300 + i * 22, w - 56, 8, "#171C29", 3)
    # the point of impact on the front
    doc.glow(x + 10, hit_y, 90, 110, red, 0.5)


def _noise(rng: random.Random, x0: float, x1: float, y: float, amp: float) -> str:
    """A signal line that gets noisier towards its end."""
    pts = [(x0, y)]
    x = x0
    while x < x1:
        x += rng.uniform(10, 22)
        t = (x - x0) / (x1 - x0)
        a = amp * (0.1 + 0.9 * t ** 1.6)
        pts.append((min(x, x1), y + rng.uniform(-a, a)))
    pts.append((x1, y))
    return "M" + "L".join(f"{f(a)} {f(b)}" for a, b in pts)


@scene("kernel_dos")
def kernel_dos(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    red = p.danger

    doc.rect(0, 0, W, H, doc.lin([(0, "#0F1828", 1), (1, "#070B13", 1)]))
    doc.rect(0, 0, W, H, doc.rad([(0, "#6F8FC8", 0.18), (1, "#6F8FC8", 0)], 0.72, 0.3, 0.5))
    floor = 760.0
    doc.rect(0, floor, W, H - floor, doc.lin([(0, "#121B2C", 1), (1, "#06090F", 1)]))
    doc.line((0, floor), (W, floor), "#2A3650", 2)

    # the tower, tipping over to the right around its right foot
    tx, tw, th = 860.0, 290.0, 560.0
    ty = floor - th
    hit_y = ty + th * 0.42
    tilt = 13.0
    # its shadow on the floor, stretched in the direction of the fall
    doc.add(f'<ellipse cx="{f(tx + tw + 140)}" cy="{f(floor + 10)}" rx="{f(tw * 1.1)}" ry="24" fill="#000" '
            f'opacity="0.6" filter="{doc.blur(14)}"/>')
    with doc.g(transform=f"rotate({tilt} {f(tx + tw)} {f(floor)})"):
        _tower(doc, tx, ty, tw, th, red, hit_y)
    # motion arcs swept by the top corners as it tips
    for cx_, cy_ in ((tx, ty), (tx + 120, ty - 70)):
        r = math.hypot(cx_ - (tx + tw), cy_ - floor)
        a0 = math.atan2(cy_ - floor, cx_ - (tx + tw))
        pts = []
        for k in range(9):
            a = a0 + math.radians(tilt * (0.15 + 0.85 * k / 8))
            pts.append((tx + tw + r * math.cos(a), floor + r * math.sin(a)))
        doc.path("M" + "L".join(f"{f(a)} {f(b)}" for a, b in pts), stroke="#9FB4D8", sw=3, opacity=0.35,
                 dash="10 10")

    # the noisy signal arriving from the left, ending at the impact point
    rad = math.radians(tilt)
    px, py = tx + tw, floor
    vx, vy = tx - px, hit_y - py
    hx = px + vx * math.cos(rad) - vy * math.sin(rad)
    hy = py + vx * math.sin(rad) + vy * math.cos(rad)
    d = _noise(rng, -10, hx - 6, hy, 70)
    doc.path(d, stroke=red, sw=10, opacity=0.18)
    doc.path(d, stroke=red, sw=4)
    doc.circle(hx - 2, hy, 9, "#FFD2C8")

    # the flaw's name, and what it affects when the sources list it
    head = text[:160]
    name = next((e for e in brief.entities if mentions(e, head) and T.supported(e, "display") == e), "")
    cves = brief.facts.get("cves") or []
    label = (str(cves[0]) if cves else "") or name
    if label:
        size = 110.0 if len(label) < 12 else 64.0
        doc.text(label, 80, 180, size, p.ink, "display")
    services = [s for s in _SERVICES if s in text][:3]
    if services:
        x = 84.0
        for s in services:
            w = T.measure(s, 34, "mono") + 36
            doc.rect(x, 230, w, 54, "none", 27, stroke="#5B6B86", sw=2)
            doc.text(s, x + 18, 267, 34, "#B7C3D8", "mono")
            x += w + 16

    doc.rect(0, 0, W, H, doc.rad([(0.6, "#000", 0), (1, "#000", 0.5)], 0.5, 0.5, 0.78))
    doc.focus = Box(40, 70, 1440, 810)
