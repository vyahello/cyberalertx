"""USB worms: one large flash drive in the foreground, its activity LED lit,
and the worm's trail of copies behind it: smaller and smaller drives along an
S-curve into the dark, the way removable-media spread travels from drive to
drive.

The worm's and the payload's names are set only when the sources name them;
the "years after takedown" tag only when `brief.facts` states the years.
Generic hardware, no vendor marks, no screens, no invented file names."""
from __future__ import annotations

import math
import random
import re

from .. import type as T
from ..brief import EditorialBrief, mentions
from ..kit import H, W, Box, Doc, f, pill
from . import scene

_DRIVE_COLORS = (("#2D3A34", "#46584F"), ("#2B3442", "#46536A"), ("#3A2F2A", "#5A4A40"), ("#30303A", "#4A4A58"))


def _usb(doc: Doc, x: float, y: float, s: float, rot: float, body: tuple[str, str], infected: bool,
         danger: str, opacity: float = 1.0) -> tuple[float, float]:
    """A flash drive, 3/4 top view, connector pointing right. (x, y) = centre.
    Returns the tip of the connector."""
    w, h = 150 * s, 52 * s
    with doc.g(f"translate({f(x)} {f(y)}) rotate({f(rot)})", opacity=opacity):
        doc.rect(-w / 2 + 6 * s, -h / 2 + 12 * s, w, h, "#000", 10 * s, opacity=0.45,
                 extra=f' filter="{doc.blur(round(8 * s) or 1)}"')
        # metal connector
        cx0 = w / 2 - 4 * s
        doc.rect(cx0, -h * 0.34, 46 * s, h * 0.68, doc.lin([(0, "#E9EDF1", 1), (0.5, "#9BA4AE", 1),
                                                           (1, "#C9D0D7", 1)]), 3 * s)
        for k in (0, 1):
            doc.rect(cx0 + 12 * s + k * 16 * s, -h * 0.12, 8 * s, 8 * s, "#59616B", 1)
        # body (with a side face for thickness)
        doc.rect(-w / 2, -h / 2 + 6 * s, w, h, body[0], 10 * s)
        doc.rect(-w / 2, -h / 2, w, h, doc.lin([(0, body[1], 1), (1, body[0], 1)]), 10 * s)
        doc.rect(-w / 2 + 6 * s, -h / 2 + 3 * s, w - 12 * s, 4 * s, "#FFFFFF", 2 * s, opacity=0.14)
        # key-ring hole and grip lines
        doc.circle(-w / 2 + 16 * s, 0, 6 * s, "#0B0F0D")
        for k in range(4):
            doc.rect(-w / 2 + 40 * s + k * 12 * s, -h / 2 + 12 * s, 3 * s, h - 24 * s, "#000", 1, opacity=0.18)
        # activity LED
        led = danger if infected else "#7CE0A8"
        doc.circle(w / 2 - 20 * s, 0, 5 * s, led)
        if infected:
            doc.circle(w / 2 - 20 * s, 0, 14 * s, led, opacity=0.25)
    a = math.radians(rot)
    tip = w / 2 + 42 * s
    return x + tip * math.cos(a), y + tip * math.sin(a)


@scene("usb_worm")
def usb_worm(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    doc.rect(0, 0, W, H, doc.lin([(0, "#13201A", 1), (1, "#060A08", 1)], 0, 0, 0.3, 1))
    doc.rect(0, 0, W, H, doc.rad([(0, "#7CE0A8", 0.12), (1, "#7CE0A8", 0)], 0.62, 0.62, 0.55))
    names = [n for n in ("Retadup", "CoffeeLoader") if mentions(n, text)]

    # the trail: copies receding along an S-curve toward the top left
    trail = [(1000, 300, 0.95, -18), (760, 200, 0.70, 8), (560, 250, 0.52, -14), (410, 170, 0.40, 10),
             (300, 220, 0.31, -8), (215, 160, 0.25, 6)]
    pts = [(1320.0, 610.0)] + [(x, y) for x, y, _, _ in trail]
    d = f"M{f(pts[0][0])} {f(pts[0][1])}"
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        mx = (x0 + x1) / 2
        d += f"C{f(mx)} {f(y0)} {f(mx)} {f(y1)} {f(x1)} {f(y1)}"
    doc.path(d, stroke=p.danger, sw=6, dash="2 15", opacity=0.9)
    for k, (x, y, sc, rot) in enumerate(reversed(trail)):
        op = 1.0
        _usb(doc, x, y, sc * 1.6, rot, _DRIVE_COLORS[(k + 1) % 4], True, p.danger, opacity=op)
    # atmospheric haze: the farther the copy, the more it fades into the dark
    doc.rect(0, 0, W, H, doc.lin([(0, "#0C1611", 0.75), (0.45, "#0C1611", 0.35), (0.8, "#0C1611", 0.0)], 0, 0, 1, 0.4))
    # the hero drive
    doc.glow(1130, 640, 420, 140, p.danger, 0.16)
    _usb(doc, 1060, 640, 4.0, -14, ("#35503F", "#7FA691"), True, p.danger)
    # rim light along the hero's upper edge
    with doc.g(f"translate(1060 640) rotate(-14)"):
        doc.rect(-290, -104, 560, 6, "#DFF5E8", 3, opacity=0.35)

    title = names[0] if names else "USB worm"
    doc.text(title, 150, 690, 84, p.ink, "display")
    y = 760
    if "CoffeeLoader" in names and title != "CoffeeLoader":
        doc.text("spreads", 152, y + 12, 30, p.muted, "ui")
        pill(doc, 152 + T.measure("spreads", 30, "ui") + 16, y - 22, "CoffeeLoader", fg="#FFFFFF", bg=p.danger,
             size=30, font="ui_bold")
    years = brief.facts.get("years")
    if years and re.search(r"takedown|taken down|seized", text):
        pill(doc, 152, 560, f"back {years} years after takedown", fg="#0B1310", bg="#F2C14E", size=24,
             font="ui_bold")
    doc.rect(0, 0, W, H, doc.rad([(0.55, "#000", 0), (1, "#000", 0.45)], 0.5, 0.5, 0.78))
    doc.focus = Box(100, 260, 1300, 731)
