"""Code signing as a seal of trust: the signature is drawn as a large wax seal
with a check in it, and a crack runs through it when the sources say the
signing infrastructure was compromised. A thin fuse along the floor leads to
the seal through the stations the sources name on the way in (for example
Log4Shell, then vCenter, then the build servers).

Nothing is a screenshot: no access log, no request line, no host names, no
certificate fields, no claim that keys were exported (unless the sources say
so). Station labels are taken only from the source text."""
from __future__ import annotations

import math
import random

from ..brief import EditorialBrief
from ..kit import Box, Doc, W, H, f, icon
from . import scene

_ATTACK = ("exploited", "confirmed", "attacks_observed", "compromise", "suspected")


def _seal(doc: Doc, cx: float, cy: float, r: float, rng: random.Random, wax: str, crack: bool,
          hot: str) -> None:
    # ribbon tails behind the seal
    for side in (-1, 1):
        x0 = cx + side * r * 0.32
        doc.poly([(x0 - r * 0.2, cy + r * 0.4), (x0 + r * 0.2, cy + r * 0.4),
                  (x0 + side * r * 0.36 + r * 0.16, cy + r * 1.55), (x0 + side * r * 0.36, cy + r * 1.38),
                  (x0 + side * r * 0.36 - r * 0.16, cy + r * 1.6)], "#7E1B16")
    doc.add(f'<circle cx="{f(cx + 14)}" cy="{f(cy + 40)}" r="{f(r)}" fill="#000" opacity="0.35" '
            f'filter="{doc.blur(26)}"/>')
    # irregular wax rim
    n = 90
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        rr = r * (1 + 0.035 * math.sin(a * 5 + 1.3) + 0.02 * (rng.random() - 0.5))
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    doc.poly(pts, doc.rad([(0, "#E5483A", 1), (0.7, wax, 1), (1, "#6E1611", 1)], 0.38, 0.32, 0.75))
    # pressed inner field and its rim
    doc.circle(cx, cy, r * 0.74, doc.rad([(0, "#B4261C", 1), (1, "#8E1A13", 1)], 0.6, 0.7, 0.7))
    doc.circle(cx, cy, r * 0.74, "none", "#F07A6A", r * 0.025, 0.55)
    doc.circle(cx, cy, r * 0.64, "none", "#5E100C", r * 0.02, 0.6)
    # the emblem: a check, the mark of a valid signature
    k = r / 100
    doc.path(f"M{f(cx - 34 * k)} {f(cy + 2 * k)}L{f(cx - 8 * k)} {f(cy + 28 * k)}L{f(cx + 38 * k)} {f(cy - 26 * k)}",
             stroke="#5E100C", sw=16 * k, opacity=0.8)
    doc.path(f"M{f(cx - 36 * k)} {f(cy - 2 * k)}L{f(cx - 10 * k)} {f(cy + 24 * k)}L{f(cx + 36 * k)} {f(cy - 30 * k)}",
             stroke="#FFB3A8", sw=12 * k)
    # highlight
    doc.path(f"M{f(cx - r * 0.78)} {f(cy - r * 0.3)}A{f(r * 0.85)} {f(r * 0.85)} 0 0 1 {f(cx - r * 0.1)} "
             f"{f(cy - r * 0.84)}", stroke="#FFFFFF", sw=r * 0.05, opacity=0.25)
    if crack:
        zig = [(cx - r * 0.18, cy - r * 1.02), (cx - r * 0.05, cy - r * 0.62), (cx - r * 0.2, cy - r * 0.3),
               (cx + r * 0.06, cy + r * 0.02), (cx - r * 0.04, cy + r * 0.34), (cx + r * 0.18, cy + r * 0.64),
               (cx + r * 0.08, cy + r * 1.03)]
        d = "M" + "L".join(f"{f(x)} {f(y)}" for x, y in zig)
        doc.glow(cx, cy, r * 0.22, r * 0.9, hot, 0.22)
        doc.path(d, stroke="#14090A", sw=r * 0.07)
        doc.path(d, stroke=hot, sw=r * 0.016)


def _stations(text: str) -> tuple[str, list[str]]:
    """(entry, stations) named in the source text, in the order of the intrusion."""
    entry = next((lab for k, lab in (("log4shell", "Log4Shell"), ("log4j", "Log4j")) if k in text), "")
    stations = []
    for k, lab in (("vcenter", "vCenter"), ("build", "build")):
        if k in text:
            stations.append(lab)
    return entry, stations


@scene("code_signing")
def code_signing(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    hot = "#FFB020"
    crack = brief.status in _ATTACK or any(k in text for k in ("compromis", "hijack", "stole", "stolen"))

    doc.rect(0, 0, W, H, doc.lin([(0, "#1C1110", 1), (1, "#0B0707", 1)]))
    doc.rect(0, 0, W, H, doc.rad([(0, "#FF8A50", 0.16), (1, "#FF8A50", 0)], 0.64, 0.42, 0.5))
    floor = 700.0
    doc.rect(0, floor, W, H - floor, doc.lin([(0, "#000", 0.0), (1, "#000", 0.4)]))

    scx, scy, sr = 1030.0, 370.0, 270.0
    entry, stations = _stations(text)

    # the fuse along the floor: entry -> stations -> the seal
    nodes = [(380.0 + i * 250, floor) for i in range(len(stations))]
    pts = [(0.0, floor)] + nodes + [(scx - sr - 150, floor)]
    d = "M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts)
    d += f"Q{f(scx - sr - 40)} {f(floor)} {f(scx - sr * 0.9)} {f(scy + sr * 0.38)}"
    if crack:
        doc.path(d, stroke=p.danger, sw=14, opacity=0.18)
    doc.path(d, stroke=p.danger if crack else p.muted, sw=5, dash="" if crack else "8 10")
    for (x, y), lab in zip(nodes, stations):
        doc.circle(x, y, 52, "#1F1514", p.danger if crack else p.muted, 4)
        icon(doc, "server", x, y, 52, p.ink, 2.6)
        doc.text(lab, x, y + 104, 40, p.ink, "ui_bold", anchor="middle")
    if entry:
        doc.text(entry, 40, floor - 36, 56, p.danger if crack else p.muted, "ui_bold")

    _seal(doc, scx, scy, sr, rng, "#B3261C", crack, hot)
    doc.text("code signing", scx, scy + sr * 1.82, 46, p.ink, "ui_bold", anchor="middle", opacity=0.85)

    doc.rect(0, 0, W, H, doc.rad([(0.62, "#000", 0), (1, "#000", 0.5)], 0.5, 0.5, 0.78))
    doc.focus = Box(0, 82, 1400, 788)
