"""Developer-tool supply chain: a stolen access key opens a marketplace to a
trojanised extension.

What the sources state (s:69560c1110e62b): an access key Cursor had issued
to Fireworks was exposed when Fireworks was breached; attackers used the
stolen credentials to push a malicious Claude Code extension through
Cursor's extension marketplace; Cursor confirmed a breach. They do not
describe the extension's code, how it ran, the key's scope or any update
mechanism, so the extension's contents are drawn redacted and nothing else
is claimed.

One subject for the feed: the marketplace listing of the extension, large,
with its contents struck out, and the stolen key itself (a physical key with
the holder's tag) turned in the listing's publishing lock. Product names are
plain text and only those the headline names; no logos, no editor UI."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from .. import type as T
from ..kit import Box, Doc, background, f, vignette
from . import scene
from ._editorial import fit_size

_ATTACK = ("exploited", "confirmed", "attacks_observed", "compromise")


def _key(doc: Doc, x: float, y: float, s: float, ang: float, holder: str, danger: str) -> None:
    """A physical key, bow at (x, y), pointing along `ang` degrees; `s` = bow
    radius. A paper tag on the bow names the holder (as the sources do)."""
    steel = doc.lin([(0, "#F2F4F7", 1), (0.45, "#AEB6C2", 1), (0.55, "#8A93A1", 1), (1, "#D9DEE5", 1)], 0, 0, 0, 1)
    L = s * 4.4
    with doc.g(transform=f"rotate({f(ang)} {f(x)} {f(y)})"):
        # cast shadow
        with doc.g(transform="translate(18 26)", opacity=0.5):
            doc.circle(x, y, s, "#000")
            doc.rect(x + s * 0.8, y - s * 0.2, L - s * 0.8, s * 0.4, "#000", s * 0.08)
            doc.add(f'<rect x="{f(x)}" y="{f(y - s)}" width="{f(L)}" height="{f(2 * s)}" fill="none" '
                    f'filter="{doc.blur(12)}"/>')
        # shaft and bit (teeth along the lower edge, near the tip)
        sy, sh = y - s * 0.19, s * 0.38
        doc.rect(x + s * 0.7, sy, L - s * 0.7, sh, steel, s * 0.05)
        doc.rect(x + s * 0.7, sy + sh * 0.42, L - s * 0.9, sh * 0.14, "#6B7482", opacity=0.6)
        tx = x + L - s * 1.7
        teeth = [0.5, 0.95, 0.65, 1.0, 0.55]
        d = f"M{f(tx)} {f(sy + sh)}"
        for i, t in enumerate(teeth):
            d += f"L{f(tx + i * s * 0.3 + s * 0.06)} {f(sy + sh + s * 0.42 * t)}H{f(tx + i * s * 0.3 + s * 0.22)}" \
                 f"L{f(tx + (i + 1) * s * 0.3)} {f(sy + sh)}"
        doc.path(d + "Z", fill=steel)
        doc.poly([(x + L, sy), (x + L + s * 0.22, sy + sh * 0.5), (x + L, sy + sh)], "#C3C9D2")
        # collar
        doc.rect(x + s * 0.78, y - s * 0.32, s * 0.22, s * 0.64, "#C3C9D2", s * 0.04, stroke="#6B7482", sw=2)
        # the bow: a ring
        ring = doc.lin([(0, "#FFFFFF", 1), (0.5, "#A6AEBA", 1), (1, "#5F6876", 1)], 0, 0, 1, 1)
        doc.add(f'<path d="M{f(x - s)} {f(y)}a{f(s)} {f(s)} 0 1 0 {f(2 * s)} 0a{f(s)} {f(s)} 0 1 0 {f(-2 * s)} 0Z'
                f'M{f(x - s * 0.42)} {f(y)}a{f(s * 0.42)} {f(s * 0.42)} 0 1 1 {f(s * 0.84)} 0'
                f'a{f(s * 0.42)} {f(s * 0.42)} 0 1 1 {f(-s * 0.84)} 0Z" fill="{ring}" fill-rule="evenodd" '
                f'stroke="#4E5664" stroke-width="2"/>')
        doc.path(f"M{f(x - s * 0.8)} {f(y - s * 0.3)}A{f(s * 0.86)} {f(s * 0.86)} 0 0 1 {f(x + s * 0.2)} "
                 f"{f(y - s * 0.84)}", stroke="#FFFFFF", sw=s * 0.08, opacity=0.7)
    # the holder's tag hangs from the bow (not rotated: it hangs by gravity)
    if holder:
        tx, ty = x - s * 0.55, y + s * 0.25
        tw, th = max(T.measure(holder, 48, "ui_bold") + 70, 300), 150
        bx, by = max(70.0, tx - tw * 0.4), ty + s * 1.25
        doc.path(f"M{f(tx)} {f(ty)}C{f(tx - 10)} {f(ty + 60)} {f(bx + 40)} {f(by - 40)} {f(bx + 34)} {f(by + 26)}",
                 stroke="#D9CBA8", sw=3)
        with doc.g(transform=f"rotate(-6 {f(bx)} {f(by)})"):
            doc.shadow(bx, by, tw, th, 10, 0.6)
            doc.path(f"M{f(bx + 30)} {f(by)}H{f(bx + tw)}V{f(by + th)}H{f(bx + 30)}L{f(bx)} {f(by + th - 30)}"
                     f"V{f(by + 30)}Z", fill="#F1E8D2")
            doc.circle(bx + 34, by + 26, 8, "#0B111C")
            doc.text("ISSUED TO", bx + 60, by + 52, 22, "#6E6656", "ui_bold", tracking=3)
            doc.text(holder, bx + 58, by + 112, 48, "#14161B", "ui_bold")
            doc.rect(bx + 30, by + th - 14, tw - 30, 14, danger, opacity=0.9)


@scene("dev_supply_chain")
def dev_supply_chain(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.62, 0.3))
    ents = list(brief.entities)
    text = brief.text or ""
    holder = next((e for e in ents if f"{e.lower()} ai" in text or f"key we had issued to {e.lower()}" in text),
                  ents[0] if len(ents) > 1 else "")
    ext = "Claude Code" if "Claude" in ents else "Extension"
    market = next((e for e in ents if e not in (holder, "Claude")), "")
    attack = brief.status in _ATTACK
    trojan = "trojaniz" in text or "троян" in text

    # ---- the listing (hero): a large card, contents struck out
    card = Box(640, 120, 900, 660)
    doc.add(f'<ellipse cx="{f(card.cx)}" cy="{f(card.cy)}" rx="620" ry="460" fill="{p.danger}" opacity="0.10" '
            f'filter="{doc.blur(90)}"/>')
    doc.shadow(card.x, card.y, card.w, card.h, 28, 1.5)
    doc.rect(card.x, card.y, card.w, card.h, doc.lin([(0, "#1E2A42", 1), (1, "#111827", 1)], 0, 0, 0.4, 1), 28,
             stroke="#33425F", sw=2)
    doc.text((market.upper() + " MARKETPLACE") if market else "EXTENSION MARKETPLACE", card.x + 64, card.y + 78, 24,
             "#8C9AB5", "ui_bold", tracking=4)
    # extension icon: a generic terminal glyph, not a logo
    ix, iy, isz = card.x + 64, card.y + 118, 150
    doc.rect(ix, iy, isz, isz, doc.lin([(0, "#2C3B5C", 1), (1, "#1B263D", 1)], 0, 0, 1, 1), 32)
    doc.path(f"M{f(ix + 40)} {f(iy + 52)}L{f(ix + 74)} {f(iy + 78)}L{f(ix + 40)} {f(iy + 104)}"
             f"M{f(ix + 86)} {f(iy + 106)}H{f(ix + 116)}", stroke="#E8EDF5", sw=11)
    size = fit_size(ext, 120, card.r - (ix + isz + 40) - 50)
    doc.text(ext, ix + isz + 40, iy + 60 + T.cap_height(size, "display") / 2, size, "#FFFFFF", "display",
             tracking=-size * 0.015)
    doc.text("extension", ix + isz + 44, iy + 150, 30, "#8C9AB5", "ui")
    # the verdict the sources give, as one strong band
    vy = card.y + 330
    verdict = "TROJANIZED" if trojan else ("MALICIOUS VERSION" if attack else "REPORTED")
    doc.rect(card.x, vy, card.w, 116, p.danger if attack or trojan else p.warn)
    vs = fit_size(verdict, 84, card.w - 128)
    doc.text(verdict, card.x + 64, vy + 58 + T.cap_height(vs, "display") / 2, vs, "#0A0F1A", "display",
             tracking=vs * 0.02)
    # contents: redacted on purpose (the sources describe no code)
    cy = vy + 150
    with doc.g(clip=doc.clip_rect(card.x + 64, cy, card.w - 128, 120, 10)):
        doc.rect(card.x + 64, cy, card.w - 128, 120, "#1A1220")
        stripes = "".join(f"M{f(card.x + 64 + i * 26)} {f(cy + 120)}l120 -120" for i in range(-6, int(card.w / 26)))
        doc.path(stripes, stroke=p.danger, sw=9, opacity=0.25, cap="butt")
    for i, w in enumerate((0.62, 0.44, 0.7)):
        doc.rect(card.x + 92, cy + 24 + i * 30, (card.w - 184) * w, 14, "#3A2232", 5)
    doc.text("contents not described in the reports", card.x + 64, cy + 158, 22, "#C9A0A8", "mono")

    # ---- the stolen key, turned in the listing's publishing lock
    lx, ly = card.x, card.y + 250
    doc.rect(lx - 34, ly - 50, 68, 100, "#0B111C", 14, stroke="#33425F", sw=2)
    doc.circle(lx, ly - 8, 12, "#000")
    doc.rect(lx - 5, ly - 8, 10, 30, "#000", 3)
    _key(doc, 200, 470, 98, -12.8, holder, p.danger)

    vignette(doc, 0.45)
    doc.focus = Box(90, 90, 1470, 827)
