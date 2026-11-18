"""Cloud breaches through a trusted party: one large key (the access a
platform or provider holds) pushed into a cloud with a keyhole; behind it,
further clouds whose keyholes glow too, because the same access reaches more
than one account when the sources say so (several customers). Records drift
out of the cloud only when the sources report data or secrets taken.

The key's tag carries the platform's or company's name from the headline;
"AWS" is set on the cloud only when the headline names it. No storage
browser, file names, addresses or console screens are drawn."""
from __future__ import annotations

import random
import re

from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, vignette
from . import scene
from ._editorial import fit_size, primary_product


def _cloud_d(cx: float, cy: float, w: float) -> str:
    h = w * 0.55
    x0, base = cx - w / 2, cy + h / 2
    return (f"M{f(x0 + w * 0.16)} {f(base)}"
            f"A{f(w * 0.16)} {f(w * 0.16)} 0 0 1 {f(x0 + w * 0.10)} {f(base - h * 0.55)}"
            f"A{f(w * 0.22)} {f(w * 0.22)} 0 0 1 {f(x0 + w * 0.42)} {f(base - h * 0.9)}"
            f"A{f(w * 0.25)} {f(w * 0.25)} 0 0 1 {f(x0 + w * 0.84)} {f(base - h * 0.62)}"
            f"A{f(w * 0.17)} {f(w * 0.17)} 0 0 1 {f(x0 + w * 0.86)} {f(base)}Z")


def _cloud(doc: Doc, cx: float, cy: float, w: float, line: str, keyhole: str, opacity: float = 1.0) -> None:
    d = _cloud_d(cx, cy, w)
    with doc.g(opacity=opacity):
        doc.path(d, fill="#000", opacity=0.16, extra=f' filter="{doc.blur(14)}" transform="translate(10 22)"')
        doc.path(d, fill=doc.lin([(0, "#FFFFFF", 1), (1, "#DCE6EF", 1)]))
        doc.path(d, stroke=line, sw=max(4.0, w / 90))
        k = w / 560
        kx, ky = cx - w * 0.04, cy + w * 0.03
        doc.glow(kx, ky, 70 * k, 70 * k, keyhole, 0.35)
        if w < 500:     # the further accounts show their keyholes; the main one has the key in it
            doc.circle(kx, ky - 16 * k, 30 * k, keyhole)
            doc.poly([(kx - 16 * k, ky), (kx + 16 * k, ky), (kx + 26 * k, ky + 62 * k),
                      (kx - 26 * k, ky + 62 * k)], keyhole)


def _key(doc: Doc, bow: tuple[float, float], tip_x: float, danger: str) -> tuple[float, float]:
    """A modern pin-tumbler key lying horizontally, head at left, blade
    entering the lock at tip_x. Returns the point where its tag hangs."""
    bx, by = bow
    steel = doc.lin([(0, "#F4F6F8", 1), (0.5, "#B7C0C8", 1), (1, "#76828D", 1)], 0, 0, 0.3, 1)
    sh = ' filter="{}" transform="translate(14 26)"'.format(doc.blur(10))
    hw, hh = 250.0, 220.0
    head = (f"M{f(bx - hw / 2 + 60)} {f(by - hh / 2)}H{f(bx + hw / 2 - 30)}Q{f(bx + hw / 2)} {f(by - hh / 2)} "
            f"{f(bx + hw / 2)} {f(by - hh / 2 + 30)}V{f(by + hh / 2 - 30)}Q{f(bx + hw / 2)} {f(by + hh / 2)} "
            f"{f(bx + hw / 2 - 30)} {f(by + hh / 2)}H{f(bx - hw / 2 + 60)}A{f(hh / 2)} {f(hh / 2)} 0 0 1 "
            f"{f(bx - hw / 2 + 60)} {f(by - hh / 2)}Z"
            f"M{f(bx - 70)} {f(by)}a34 34 0 1 0 68 0a34 34 0 1 0 -68 0Z")
    x0 = bx + hw / 2 - 4
    # blade: flat bottom, cut (bitted) top edge, ending at the lock
    d = f"M{f(x0)} {f(by - 44)}H{f(x0 + 60)}"
    x = x0 + 60
    k = 0
    while x < tip_x - 70:
        dep = (18, 34, 10, 28, 22, 36, 14)[k % 7]
        d += f"L{f(x + 22)} {f(by - 44 + dep)}L{f(x + 44)} {f(by - 44)}"
        x += 44
        k += 1
    d += f"H{f(tip_x)}V{f(by + 40)}H{f(x0)}Z"
    for dd in (head, d):
        doc.path(dd, fill="#000", opacity=0.22, extra=' fill-rule="evenodd"' + sh)
    for dd in (head, d):
        doc.path(dd, fill=steel, extra=' fill-rule="evenodd"')
    doc.path(f"M{f(x0 + 10)} {f(by + 8)}H{f(tip_x - 6)}", stroke="#76828D", sw=6, opacity=0.8)
    doc.path(f"M{f(x0 + 10)} {f(by + 20)}H{f(tip_x - 6)}", stroke="#FFFFFF", sw=3, opacity=0.5)
    # where the key enters the lock
    doc.add(f'<ellipse cx="{f(tip_x)}" cy="{f(by)}" rx="16" ry="52" fill="{danger}"/>')
    doc.add(f'<ellipse cx="{f(tip_x + 4)}" cy="{f(by)}" rx="8" ry="36" fill="#5A0F0A"/>')
    return bx - hw * 0.3, by + hh * 0.42


@scene("cloud_breach")
def cloud_breach(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    background(doc, light=(0.4, 0.2))
    several = re.search(r"multiple|customers'|customer accounts|several|accounts", text) is not None
    taken = re.search(r"steal|stole|exfiltrat|secrets", text) is not None
    if several:          # further accounts reached with the same access
        _cloud(doc, 1330, 230, 360, p.line, p.danger, opacity=0.75)
        _cloud(doc, 1360, 720, 330, p.line, p.danger, opacity=0.6)
    _cloud(doc, 1060, 470, 640, p.accent, p.danger)
    if "AWS" in brief.entities:
        doc.text("AWS", 1060 + 130, 470 + 24, 76, p.accent, "display", anchor="middle")
    if taken:
        for k, (x, y, rot) in enumerate(((1400, 520, 10), (1500, 470, -6), (1570, 400, 14))):
            with doc.g(f"rotate({rot} {x} {y})", opacity=1 - k * 0.2):
                doc.rect(x - 34, y - 44, 68, 88, "#FFFFFF", 5, stroke=p.danger, sw=3)
                for j in range(4):
                    doc.rect(x - 22, y - 28 + j * 16, 44 - (j % 2) * 14, 6, p.muted, 3)
        doc.path("M1320 560C1400 540 1480 490 1600 380", stroke=p.danger, sw=4, dash="4 14", opacity=0.8)
    # the key, its bit inside the cloud's keyhole
    tag = _key(doc, (300, 490), 1034, p.danger)
    name = primary_product(brief)[0]
    if name and name != "AWS":
        size = fit_size(name, 50, 340, "display")
        tw = min(340.0, max(200.0, size * 0.62 * len(name))) + 50
        tx, ty = tag[0] - 40, tag[1] + 50
        doc.line((tag[0] + 20, tag[1] - 10), (tx + 30, ty + 6), "#5B6B7D", 3)
        with doc.g(f"rotate(-8 {f(tx)} {f(ty)})"):
            doc.rect(tx + 6, ty + 14, tw, 96, "#000", 10, opacity=0.16, extra=f' filter="{doc.blur(6)}"')
            doc.rect(tx, ty, tw, 96, "#FFFFFF", 10, stroke=p.line, sw=2)
            doc.circle(tx + 26, ty + 48, 9, p.bg1, p.line, 2)
            doc.text(name, tx + 48, ty + 48 + size * 0.36, size, p.ink, "display")
    doc.focus = Box(60, 120, 1420, 799)
    vignette(doc, 0.3)
    _ = rng
