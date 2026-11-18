"""Compromised company websites used against their own visitors, as a street
of facades: the sites stand in a row that recedes into the distance, the
ones the headline names in front, dozens of anonymous ones behind. Every
facade carries the same injected block at the same place. In the foreground
the two things the sources say were targeted: a phone (when iPhones/iOS are
named) and a coin (when crypto theft is named).

No page is a screenshot: the facades are silhouettes, the injected script an
abstract block, there is no wallet dialog, no code, no domain. Site names are
plain text and only those the headline names (brief.entities)."""
from __future__ import annotations

import random
import re

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, W, H, f, icon
from . import scene

_ATTACK = ("exploited", "confirmed", "attacks_observed", "compromise")


def _phone(doc: Doc, x: float, y: float, w: float, h: float, red: str, hot: bool) -> None:
    r = w * 0.17
    doc.rect(x + 10, y + 30, w, h, "#000", r, opacity=0.55, extra=f' filter="{doc.blur(18)}"')
    doc.rect(x, y, w, h, doc.lin([(0, "#5A5F6B", 1), (0.5, "#2B2E35", 1), (1, "#5D626D", 1)], 0, 0, 1, 0), r)
    bz = w * 0.05
    sx, sy, sw_, sh = x + bz, y + bz, w - 2 * bz, h - 2 * bz
    doc.rect(sx, sy, sw_, sh, "#0B0E15", r - bz)
    if hot:
        doc.rect(sx, sy, sw_, sh, doc.rad([(0, red, 0.55), (1, red, 0.05)], 0.5, 0.55, 0.7), r - bz)
        icon(doc, "warn", sx + sw_ / 2, sy + sh * 0.52, sw_ * 0.5, "#FFFFFF", 3.2)
    doc.rect(sx + sw_ / 2 - w * 0.15, sy + w * 0.05, w * 0.3, w * 0.08, "#000", w * 0.04)
    doc.path(f"M{f(sx)} {f(sy + sh * 0.2)}L{f(sx + sw_ * 0.6)} {f(sy)}H{f(sx + sw_ * 0.85)}L{f(sx)} "
             f"{f(sy + sh * 0.55)}Z", fill="#FFFFFF", opacity=0.07)


def _coin(doc: Doc, cx: float, cy: float, r: float, gold: str) -> None:
    doc.add(f'<ellipse cx="{f(cx + 8)}" cy="{f(cy + r + 18)}" rx="{f(r * 0.9)}" ry="{f(r * 0.18)}" fill="#000" '
            f'opacity="0.5" filter="{doc.blur(8)}"/>')
    doc.add(f'<ellipse cx="{f(cx)}" cy="{f(cy + r * 0.12)}" rx="{f(r * 0.62)}" ry="{f(r)}" fill="#9A6A12"/>')
    doc.add(f'<ellipse cx="{f(cx - r * 0.1)}" cy="{f(cy)}" rx="{f(r * 0.62)}" ry="{f(r)}" fill="{gold}" '
            f'stroke="#FFE4A3" stroke-width="2"/>')
    doc.add(f'<ellipse cx="{f(cx - r * 0.1)}" cy="{f(cy)}" rx="{f(r * 0.44)}" ry="{f(r * 0.74)}" fill="none" '
            f'stroke="#8A5B08" stroke-width="{f(r * 0.06)}" opacity="0.7"/>')


class _Slab:
    """One facade as a section of a strip that recedes to a vanishing point:
    maps page coordinates (u, v) in [0, 1] onto the picture plane."""

    def __init__(self, x0: float, w: float, top: float, base: float, vx: float, vy: float) -> None:
        self.x0, self.w, self.top, self.base, self.vx, self.vy = x0, w, top, base, vx, vy

    def pt(self, u: float, v: float) -> tuple[float, float]:
        x = self.x0 + u * self.w
        k = (x - self.x0) / (self.vx - self.x0)
        t = self.top + (self.vy - self.top) * k
        b = self.base + (self.vy - self.base) * k
        return x, t + (b - t) * v

    def quad(self, doc: Doc, u0: float, v0: float, u1: float, v1: float, fill: str, opacity: float = 1.0) -> None:
        doc.poly([self.pt(u0, v0), self.pt(u1, v0), self.pt(u1, v1), self.pt(u0, v1)], fill, opacity=opacity)

    def slope(self, v: float) -> float:
        y0 = self.top + (self.base - self.top) * v
        return (self.vy - y0) / (self.vx - self.x0)


def _facade(doc: Doc, sl: _Slab, *, name: str, red: str, tainted: bool, rng: random.Random, dim: float) -> None:
    hgt = sl.base - sl.top
    # shadow behind the slab
    a, b = sl.pt(0, 1), sl.pt(1, 1)
    doc.add(f'<ellipse cx="{f((a[0] + b[0]) / 2)}" cy="{f((a[1] + b[1]) / 2 + 6)}" rx="{f(sl.w * 0.6)}" '
            f'ry="{f(hgt * 0.025)}" fill="#000" opacity="0.6" filter="{doc.blur(8)}"/>')
    sl.quad(doc, 0, 0, 1, 1, "#E6EAF1")
    sl.quad(doc, 0, 0, 1, 0.09, "#C3CCDA")
    for i in range(3):
        sl.quad(doc, 0.05 + i * 0.05, 0.035, 0.08 + i * 0.05, 0.055, "#8A95A8")
    if name:
        size = hgt * 0.1
        tw = T.measure(T.supported(name, "display"), size, "display")
        size = min(size, size * (sl.w * 0.84) / max(tw, 1))
        x, y = sl.pt(0.08, 0.25)
        with doc.g(transform=f"matrix(1 {sl.slope(0.25):.4f} 0 1 {f(x)} {f(y)})"):
            doc.text(name, 0, 0, size, "#141B2A", "display")
    else:
        sl.quad(doc, 0.08, 0.15, 0.08 + 0.3 + 0.3 * rng.random(), 0.24, "#5D6A80")
    sl.quad(doc, 0.08, 0.32, 0.92, 0.6, "#A6B1C2")
    for i, wv in enumerate((0.8, 0.62, 0.7)):
        sl.quad(doc, 0.08, 0.66 + i * 0.065, 0.08 + wv * 0.84, 0.69 + i * 0.065, "#C2CAD6")
    if tainted:
        sl.quad(doc, 0.6, 0.85, 0.92, 0.95, red)
    if dim < 1:
        sl.quad(doc, 0, 0, 1, 1, "#0A1020", opacity=1 - dim)


def _single(brief: EditorialBrief) -> bool:
    """One site in the headline (no plural, no count): never draw a row of them."""
    head = (brief.headline or (brief.text or "")[:200]).lower()
    return re.search(r"\bsites\b|websites|сайти|сайтів|dozens|десятк|\b\d+\s", head) is None


def alt_for(brief: EditorialBrief) -> tuple[str, str] | None:
    if not _single(brief):
        return None
    return ("Illustration: a compromised website carrying an injected element.",
            "Ілюстрація: зламаний вебсайт із вбудованим стороннім елементом.")


@scene("compromised_sites")
def compromised_sites(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    attack = brief.status in _ATTACK
    red = p.danger
    head = text[:200]
    names = [e for e in brief.entities if T.supported(e, "display") == e and e.lower() in head][:3]
    phone = any(k in text for k in ("iphone", "ios", "apple"))
    coin = any(k in text for k in ("crypto", "криптовалют", "wallet", "гаман"))

    # dusk street: cool sky to dark ground
    doc.rect(0, 0, W, H, doc.lin([(0, "#18233A", 1), (0.62, "#0D1322", 1), (1, "#06090F", 1)]))
    doc.rect(0, 0, W, H, doc.rad([(0, "#7FA0D8", 0.18), (1, "#7FA0D8", 0)], 0.84, 0.36, 0.42))
    vx, vy = 1560.0, 400.0                        # vanishing point

    # the row: named facades in front, dozens of anonymous ones receding
    x0, t0, b0 = 480.0, 110.0, 820.0
    slabs: list[_Slab] = []
    x = x0
    while x < vx - 40 and len(slabs) < 14:
        k = (x - x0) / (vx - x0)
        hgt = (b0 - t0) * (1 - k)
        w = hgt * 0.5
        slabs.append(_Slab(x, w, t0 + (vy - t0) * k, b0 + (vy - b0) * k, vx, vy))
        x += w + hgt * 0.07
    if _single(brief):
        slabs = slabs[:1]                        # the headline names one site: draw one
    for i in reversed(range(len(slabs))):
        _facade(doc, slabs[i], name=names[i] if i < len(names) else "", red=red, tainted=attack, rng=rng,
                dim=max(0.3, 1 - i * 0.1))

    # the targets in the foreground
    if attack and phone:
        doc.glow(200, 560, 200, 260, red, 0.18)
        with doc.g(transform="rotate(-7 200 560)"):
            _phone(doc, 75, 300, 250, 500, red, True)
    if attack and coin:
        doc.glow(420, 752, 80, 80, "#F5B83D", 0.22)
        _coin(doc, 420, 752, 62, "#F5B83D")

    doc.rect(0, 0, W, H, doc.rad([(0.6, "#000", 0), (1, "#000", 0.5)], 0.5, 0.5, 0.78))
    doc.focus = Box(30, 60, 1460, 821)
