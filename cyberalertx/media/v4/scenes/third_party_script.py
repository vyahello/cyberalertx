"""Third-party script supply chain as a one-to-many graphic: one hosted
JavaScript file in the centre, the websites that include it in a ring around
it, each carrying the same tainted block at the same place, all on threads
back to the one file.

The sources state the mechanism (a shared script was changed and malicious
JavaScript loaded on the sites that include it) and, at most, the vendor.
So there is no code listing, no domain, no file name and no site names
(unless the headline names them): the file is a symbol, the injected part an
abstract block, the sites anonymous page silhouettes. The vendor appears only
as plain text when the headline's subject names it."""
from __future__ import annotations

import math
import random

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, W, H, f
from . import scene

_ATTACK = ("exploited", "confirmed", "attacks_observed", "compromise")


def _vendor(brief: EditorialBrief) -> str:
    head = (brief.text or "")[:160]
    for e in brief.entities:
        if e.lower() in head and T.supported(e, "display") == e:
            return e
    return ""


def _page(doc: Doc, cx: float, cy: float, w: float, rng: random.Random, red: str, tainted: bool,
          dim: float) -> None:
    """A website as a silhouette: a light page with a header bar, a hero block
    and text bars. The tainted block sits at the same place on every page."""
    h = w * 0.68
    x, y = cx - w / 2, cy - h / 2
    doc.rect(x + 4, y + 14, w, h, "#000", 8, opacity=0.5, extra=f' filter="{doc.blur(9)}"')
    doc.rect(x, y, w, h, "#E9EDF4", w * 0.04)
    doc.rect(x, y, w, h * 0.13, "#C9D1DE", w * 0.04)
    doc.rect(x, y + h * 0.09, w, h * 0.04, "#C9D1DE")
    for i in range(3):
        doc.circle(x + w * (0.06 + i * 0.045), y + h * 0.065, w * 0.012, "#8D97A8")
    layout = rng.randrange(3)
    if layout == 0:
        doc.rect(x + w * 0.07, y + h * 0.22, w * 0.5, h * 0.36, "#9FAABB", 3)
        for i in range(3):
            doc.rect(x + w * 0.62, y + h * (0.24 + i * 0.12), w * 0.3, h * 0.05, "#B9C2D0", 2)
    elif layout == 1:
        doc.rect(x + w * 0.2, y + h * 0.22, w * 0.6, h * 0.08, "#5D6A80", 2)
        doc.rect(x + w * 0.3, y + h * 0.36, w * 0.4, h * 0.05, "#B9C2D0", 2)
        doc.rect(x + w * 0.38, y + h * 0.47, w * 0.24, h * 0.1, "#5C7FD6", h * 0.05)
    else:
        for i in range(3):
            doc.rect(x + w * (0.07 + i * 0.3), y + h * 0.22, w * 0.26, h * 0.32, "#AEB8C7", 3)
    for i in range(2):
        doc.rect(x + w * 0.07, y + h * (0.66 + i * 0.1), w * (0.7 - i * 0.25), h * 0.045, "#C3CBD7", 2)
    if tainted:
        doc.rect(x + w * 0.74, y + h * 0.7, w * 0.19, h * 0.19, red, 3)
    if dim < 1:
        doc.rect(x, y, w, h, "#0B101B", w * 0.04, opacity=1 - dim)


def _file(doc: Doc, cx: float, cy: float, w: float, h: float, red: str, ink: str, vendor: str,
          tainted: bool) -> None:
    """The shared script: one page-shaped file with a folded corner. Its body is
    abstract bars; the injected part is a red band."""
    x, y = cx - w / 2, cy - h / 2
    fold = w * 0.2
    doc.add(f'<path d="M{f(x + 14)} {f(y + 40)}h{f(w)}v{f(h)}h{f(-w)}Z" fill="#000" opacity="0.6" '
            f'filter="{doc.blur(22)}"/>')
    d = f"M{f(x)} {f(y)}H{f(x + w - fold)}L{f(x + w)} {f(y + fold)}V{f(y + h)}H{f(x)}Z"
    doc.path(d, fill=doc.lin([(0, "#FFFFFF", 1), (1, "#D9DFEA", 1)]), stroke="#FFFFFF", sw=2)
    doc.path(f"M{f(x + w - fold)} {f(y)}V{f(y + fold)}H{f(x + w)}Z", fill="#AEB7C7")
    doc.text(".js", x + w * 0.12, y + h * 0.34, w * 0.36, "#141B2A", "display")
    rows = [0.46, 0.53, 0.60, 0.67, 0.74, 0.81, 0.88]
    for i, r in enumerate(rows):
        bad = tainted and i in (3, 4, 5)
        bw = (0.76, 0.6, 0.7, 0.66, 0.74, 0.5, 0.62)[i]
        if bad:
            doc.rect(x + 6, y + h * (r - 0.025), w - 12, h * 0.07, red, 0, opacity=0.16)
        doc.rect(x + w * 0.12, y + h * r, w * bw, h * 0.03, red if bad else "#9AA5B8", h * 0.015)
    if tainted:
        doc.rect(x, y + h * (0.635 - 0.03), 8, h * 0.21, red)
    if vendor:
        size = 60.0
        tw = T.measure(T.supported(vendor, "ui_bold"), size, "ui_bold")
        doc.rect(cx - tw / 2 - 24, y + h + 26, tw + 48, 84, "#0B101B", 42, opacity=0.92)
        doc.text(vendor, cx, y + h + 89, size, ink, "ui_bold", anchor="middle")


@scene("third_party_script")
def third_party_script(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    red = p.danger
    tainted = brief.status in _ATTACK or "malicious" in (brief.text or "")
    vendor = _vendor(brief)

    doc.rect(0, 0, W, H, doc.rad([(0, "#1A2336", 1), (0.7, "#0B101B", 1), (1, "#070A11", 1)], 0.5, 0.45, 0.75))
    cx, cy = 800.0, 390.0
    if tainted:
        doc.glow(cx, cy, 360, 300, red, 0.18)

    # the ring of sites, back half first so the near ones overlap the threads
    n = 12
    sites = []
    for i in range(n):
        a = -math.pi / 2 + (i + 0.5) * 2 * math.pi / n
        sx, sy = cx + 560 * math.cos(a), cy + 30 + 300 * math.sin(a)
        depth = (math.sin(a) + 1) / 2                      # 0 = far (top), 1 = near (bottom)
        sites.append((depth, sx, sy, 140 + 80 * depth))
    sites.sort()
    for depth, sx, sy, w in sites:
        doc.line((cx, cy), (sx, sy), red if tainted else "#7D8AA3", 1.5 + 2 * depth, 0.35 + 0.45 * depth)
    for depth, sx, sy, w in sites:
        _page(doc, sx, sy, w, rng, red, tainted, 0.55 + 0.45 * depth)

    _file(doc, cx, cy - 40, 330, 410, red, p.ink, vendor, tainted)

    doc.rect(0, 0, W, H, doc.rad([(0.62, "#000", 0), (1, "#000", 0.45)], 0.5, 0.5, 0.75))
    doc.focus = Box(170, 40, 1260, 709)
