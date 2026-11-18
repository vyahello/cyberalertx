"""Cryptocurrency taken from its owner. The reported amount is the subject:
it is set very large and drains away (alternative a), or a wallet empties
as a stream of plain coins (alternative b).

Only the amount from `brief.facts` is drawn. No coin logos or ticker
symbols, no addresses, no exchange or agency names, no transaction route:
the sources state that funds were stolen, not how they moved."""
from __future__ import annotations

import random
from typing import Callable

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, vignette
from . import scene
from ._editorial import fit_size

_GOLD = ("#FFE08A", "#F5B931", "#C98A12", "#8A5A06")


def _amount(brief: EditorialBrief) -> str:
    v = str(brief.facts.get("money") or "")
    if not v:
        return ""
    if brief.facts.get("money_approx"):
        return "~" + v
    if brief.facts.get("money_plus"):
        return v + "+"
    return v


def _glyph_clip(doc: Doc, s: str, x: float, y: float, size: float) -> tuple[str, str, float]:
    """(clip url, path svg, width) for the run `s` set at (x, y)."""
    svg, w = T.text_path(s, x, y, size, font="display", fill="#000")
    doc.labels.append(T.supported(s, "display").strip())      # drawn as a clip: still visible text
    cid = doc._def(f"glyphclip{s}{x}{y}{size}", f'<clipPath id="{{id}}">{svg}</clipPath>')
    return f"url(#{cid})", svg, w


def _drop(doc: Doc, x: float, y: float, r: float, fill: str, opacity: float = 1.0) -> None:
    """A falling drop: round bottom, pointed top."""
    doc.path(f"M{f(x)} {f(y - r * 2.6)}C{f(x + r * 0.35)} {f(y - r * 1.4)} {f(x + r)} {f(y - r * 0.8)} {f(x + r)} "
             f"{f(y)}A{f(r)} {f(r)} 0 0 1 {f(x - r)} {f(y)}C{f(x - r)} {f(y - r * 0.8)} {f(x - r * 0.35)} "
             f"{f(y - r * 1.4)} {f(x)} {f(y - r * 2.6)}Z", fill=fill, opacity=opacity)


# ---------------------------------------------------------------- a: the draining figure

def _comp_drain(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    """A: the stolen amount as an emptied vessel. The figure is drawn hollow,
    a low level of gold left in it, the rest dripping out through the base
    of the glyphs into the dark."""
    p = doc.pal
    background(doc, light=(0.5, 0.18))
    amount = _amount(brief) or "crypto"
    size = fit_size(amount, 470, 1340, "display")
    cap = T.cap_height(size, "display")
    base = 200 + cap
    w = T.measure(T.supported(amount, "display"), size, "display")
    x0 = 800 - w / 2
    clip, svg, w = _glyph_clip(doc, amount, x0, base, size)
    # glow of what was there
    doc.glow(800, base - cap * 0.5, w * 0.55, cap * 0.75, _GOLD[1], 0.10)
    # the empty glyphs: dark glass with a lit rim
    k = size / 1000
    doc.add(svg.replace('fill="#000"', 'fill="#121A2A"'))
    with doc.g(clip=clip):
        doc.rect(x0 - 20, base - cap - 20, w + 40, cap * 0.45, doc.lin([(0, "#FFFFFF", 0.10), (1, "#FFFFFF", 0)]))
        # what is left: a low gold level with a wavy surface
        lvl = base - cap * 0.3
        d = f"M{f(x0 - 40)} {f(lvl)}"
        xx = x0 - 40
        i = 0
        while xx < x0 + w + 40:
            amp = 7 if i % 2 else -7
            d += f"Q{f(xx + 30)} {f(lvl + amp)} {f(xx + 60)} {f(lvl)}"
            xx += 60
            i += 1
        d += f"V{f(base + 60)}H{f(x0 - 40)}Z"
        doc.path(d, fill=doc.lin([(0, _GOLD[0], 1), (0.35, _GOLD[1], 1), (1, _GOLD[2], 1)]))
        doc.path(d.split("V")[0], stroke="#FFF3C4", sw=4, opacity=0.9)
    doc.add(svg.replace('fill="#000"', f'fill="none" stroke="{_GOLD[1]}" stroke-width="{f(5 / k)}" '
                                       f'opacity="0.85"'))
    # drips leave from the bottom edge of each glyph (stems of M, bowls of 2/5/6, the stem of $)
    xs: list[tuple[float, float]] = []
    pen = x0
    for ch in T.supported(amount, "display"):
        adv = T.measure(ch, size, "display")
        if ch in "M":
            xs += [(pen + adv * 0.16, 0.0), (pen + adv * 0.84, 0.0)]
        elif ch == ",":
            xs.append((pen + adv * 0.42, cap * 0.16))
        elif ch == "$":
            xs.append((pen + adv * 0.5, cap * 0.1))
        elif ch.strip():
            xs.append((pen + adv * 0.5, 0.0))
        pen += adv
    for i, (sx, below) in enumerate(xs):
        n = 2 + (i * 5 + rng.randrange(3)) % 3
        top = base + below + 6
        # a thin trickle, then drops spaced further apart as they fall
        tl = rng.uniform(26, 70)
        doc.path(f"M{f(sx - 5)} {f(top - 10)}Q{f(sx - 2)} {f(top + tl * 0.5)} {f(sx)} {f(top + tl)}"
                 f"Q{f(sx + 2)} {f(top + tl * 0.5)} {f(sx + 5)} {f(top - 10)}Z", fill=_GOLD[1])
        _drop(doc, sx, top + tl + 10, 8, _GOLD[1])
        yy = top + tl + 10
        for j in range(n):
            yy += 60 + j * 46 + rng.uniform(0, 30)
            if yy > 870:
                break
            _drop(doc, sx + rng.uniform(-3, 3), yy, 9 - j * 1.3, _GOLD[1], 0.95 - j * 0.18)
    doc.text("STOLEN", x0 + 10, base - cap - 74, 44, p.danger, "ui_bold", tracking=14)
    fw = max(w, 980) + 100
    doc.focus = Box(800 - fw / 2, base - cap - 150, fw, fw * 9 / 16)


# ---------------------------------------------------------------- b: the emptying wallet

def _coin(doc: Doc, cx: float, cy: float, r: float, tilt: float, rot: float) -> None:
    """A plain coin (no symbol), seen at `tilt` (0 = edge-on, 1 = face-on)."""
    ry = max(0.18, tilt) * r
    with doc.g(transform=f"rotate({rot:.1f} {f(cx)} {f(cy)})"):
        th = r * 0.16
        doc.add(f'<ellipse cx="{f(cx)}" cy="{f(cy + th)}" rx="{f(r)}" ry="{f(ry)}" fill="{_GOLD[3]}"/>')
        doc.rect(cx - r, cy, 2 * r, th, _GOLD[3])
        doc.add(f'<ellipse cx="{f(cx)}" cy="{f(cy)}" rx="{f(r)}" ry="{f(ry)}" '
                f'fill="{doc.lin([(0, _GOLD[0], 1), (0.6, _GOLD[1], 1), (1, _GOLD[2], 1)], 0, 0, 1, 1)}"/>')
        doc.add(f'<ellipse cx="{f(cx)}" cy="{f(cy)}" rx="{f(r * 0.74)}" ry="{f(ry * 0.74)}" fill="none" '
                f'stroke="{_GOLD[2]}" stroke-width="{f(max(1.5, r * 0.06))}" opacity="0.8"/>')
    vignette(doc, 0.5)


def _comp_wallet(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    """B: a wallet tipped over, a stream of plain coins pouring out of it."""
    p = doc.pal
    background(doc, light=(0.3, 0.2), floor=700)
    amount = _amount(brief)
    # wallet: a leather bifold seen from the front, tipped
    wx, wy, ww, wh = 170, 230, 620, 400
    with doc.g(transform="rotate(-14 480 430)"):
        doc.shadow(wx, wy, ww, wh, 34, 1.4)
        doc.rect(wx, wy, ww, wh, doc.lin([(0, "#3C2A22", 1), (1, "#1E140F", 1)], 0, 0, 1, 1), 34)
        doc.rect(wx + 16, wy + 16, ww - 32, wh - 32, "none", 24, stroke="#6B4E3D", sw=3,
                 extra=' stroke-dasharray="12 9"')
        # open pocket along the right edge, coins inside
        doc.rect(wx + ww - 70, wy + 40, 46, wh - 80, "#0E0907", 18)
        for k in range(4):
            _coin(doc, wx + ww - 40, wy + 90 + k * 70, 34, 0.25, 90)
        doc.rect(wx, wy, ww, wh * 0.4, doc.lin([(0, "#FFFFFF", 0.10), (1, "#FFFFFF", 0)]), 34)
    # the stream: coins tumbling from the pocket down to the right
    pts = []
    for i in range(26):
        t = i / 25
        x = 780 + t * 640 + rng.uniform(-30, 30)
        y = 300 + 520 * t * t + rng.uniform(-40, 40) + t * 30
        pts.append((x, y, 42 - 14 * t + rng.uniform(-4, 4)))
    for x, y, r in sorted(pts, key=lambda q: q[2]):
        if y < 880:
            _coin(doc, x, y, r, rng.uniform(0.2, 0.95), rng.uniform(-50, 50))
    if amount:
        sz = fit_size(amount, 210, 760, "display")
        doc.text(amount, 1520, 250, sz, p.ink, "display", anchor="end")
        doc.text("STOLEN", 1520, 320, 40, p.danger, "ui_bold", anchor="end", tracking=12)
    doc.focus = Box(120, 60, 1440, 810)


ALTERNATIVES: dict[str, Callable[[Doc, EditorialBrief, random.Random], None]] = {"a": _comp_drain,
                                                                                  "b": _comp_wallet}


@scene("crypto_theft")
def crypto_theft(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    _comp_drain(doc, brief, rng)



def alt_for(brief: EditorialBrief) -> tuple[str, str] | None:
    """Without a stated amount the scene drains the word 'crypto', not a figure."""
    if _amount(brief):
        return None
    return ("Illustration: the word 'crypto' set in large hollow letters that are draining empty, marked 'STOLEN'.",
            "Ілюстрація: слово «crypto» великими порожніми літерами, що витікають, з написом «STOLEN».")
