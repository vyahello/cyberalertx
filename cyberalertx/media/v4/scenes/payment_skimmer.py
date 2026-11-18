"""Card details stolen from a website's checkout page. The subject is a
generic card-payment form; a hidden layer behind it repeats the card
fields, so what the customer types is copied as they pay.

The form carries no brand, logo or product UI of the named company, and
every card value is a masked placeholder. No code, script name, domain or
exfiltration route is drawn: the sources say card details entered on the
checkout pages were stolen, not how."""
from __future__ import annotations

import random
from typing import Callable

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, vignette
from . import scene

_INK = "#0F1B2A"
_MUTED = "#6A7A8C"
_FIELD = "#F3F6F9"
_EDGE = "#C3CFDB"


def _dots(doc: Doc, x: float, cy: float, groups: int, per: int, r: float, color: str, gap: float = 0) -> float:
    """Masked digits as dots, `groups` groups of `per`. Returns the end x."""
    step = r * 2.9
    gap = gap or r * 3.2
    for g in range(groups):
        for i in range(per):
            doc.circle(x + r + i * step, cy, r, color)
        x += per * step + gap
    return x


def _form(doc: Doc, b: Box, *, ink: str = _INK, muted: str = _MUTED, field: str = _FIELD, edge: str = _EDGE,
          dots: str = _INK, button: str = "", panel: str = "#FFFFFF", copy: bool = False) -> list[Box]:
    """A card-payment form inside `b`. Returns the field boxes (number,
    expiry, code). With `copy` it draws only outlines (the skimmer's copy)."""
    pad = 56
    x = b.x + pad
    w = b.w - 2 * pad
    if not copy:
        doc.rect(b.x, b.y, b.w, b.h, panel, 22)
    doc.text("Card number", x, b.y + 104, 28, muted, "ui")
    num = Box(x, b.y + 124, w, 108)
    exp = Box(x, num.b + 84, (w - 36) * 0.55, 108)
    cvc = Box(exp.r + 36, exp.y, w - exp.w - 36, 108)
    doc.text("Expiry", exp.x, exp.y - 20, 28, muted, "ui")
    doc.text("CVC", cvc.x, cvc.y - 20, 28, muted, "ui")
    for fb in (num, exp, cvc):
        if copy:
            doc.rect(fb.x, fb.y, fb.w, fb.h, "none", 14, stroke=edge, sw=3, extra=' stroke-dasharray="14 10"')
        else:
            doc.rect(fb.x, fb.y, fb.w, fb.h, field, 14, stroke=edge, sw=2.5)
    r = 10.5
    _dots(doc, num.x + 34, num.cy, 4, 4, r, dots)
    _dots(doc, exp.x + 34, exp.cy, 2, 2, r, dots, gap=r * 5)
    _dots(doc, cvc.x + 34, cvc.cy, 1, 3, r, dots)
    if not copy:
        # caret in the code field: the customer is typing
        doc.rect(cvc.x + 34 + 3 * r * 2.9 + 4, cvc.cy - 26, 4, 52, button or ink)
        pb = Box(x, cvc.b + 56, w, 112)
        doc.rect(pb.x, pb.y + 8, pb.w, pb.h, "#000", 18, opacity=0.12, extra=f' filter="{doc.blur(8)}"')
        doc.rect(pb.x, pb.y, pb.w, pb.h, button or ink, 18)
        doc.text("Pay", pb.cx, pb.cy + T.cap_height(44, "ui_bold") / 2, 44, "#FFFFFF", "ui_bold", anchor="middle")
        doc.text("Checkout", x, b.y + 50, 30, ink, "ui_bold")
    return [num, exp, cvc]


# ---------------------------------------------------------------- a: carbon copy

def _comp_copy(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    """A: the form on top; a dark copy of its card fields slides out from
    underneath, like carbon paper, every field traced in red."""
    p = doc.pal
    background(doc, light=(0.3, 0.15))
    red = p.danger
    fb = Box(170, 90, 820, 760)
    cb = Box(fb.x + 470, fb.y + 70, 820, 720)
    with doc.g(transform="rotate(-2.5 600 470)"):
        # the hidden copy layer behind the form
        doc.shadow(cb.x, cb.y, cb.w, cb.h, 22, 1.2)
        doc.rect(cb.x, cb.y, cb.w, cb.h, doc.lin([(0, "#2A1216", 1), (1, "#170A0D", 1)], 0, 0, 1, 1), 22)
        doc.rect(cb.x, cb.y, cb.w, cb.h, "none", 22, stroke=red, sw=2, opacity=0.6)
        _form(doc, Box(cb.x, cb.y, cb.w, cb.h), ink=red, muted="#B86A70", edge=red, dots="#FF8A80", copy=True)
        # the form itself
        doc.shadow(fb.x, fb.y, fb.w, fb.h, 22, 1.4)
        _form(doc, fb, button=p.accent)
    doc.focus = Box(140, 70, 1330, 748)
    vignette(doc, 0.35)


# ---------------------------------------------------------------- b: peeled page

def _comp_peel(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    """B: the checkout page with its corner peeled back; underneath, a dark
    layer holds the same card fields, already filled in."""
    p = doc.pal
    background(doc, light=(0.25, 0.2))
    red = p.danger
    pg = Box(330, 120, 940, 664)
    # under-layer, same size as the page (only visible where the page peels)
    doc.shadow(pg.x, pg.y, pg.w, pg.h, 22, 1.4)
    doc.rect(pg.x, pg.y, pg.w, pg.h, doc.lin([(0, "#2A1216", 1), (1, "#130709", 1)], 0, 0, 1, 1), 22)
    _form(doc, Box(pg.x + 30, pg.y, pg.w - 60, pg.h), ink=red, muted="#B86A70", edge=red, dots="#FF8A80", copy=True)
    # the page with its top-right corner folded back along a diagonal
    fx0, fy0 = pg.r - 560, pg.y          # fold line: top edge point
    fx1, fy1 = pg.r, pg.y + 520          # right edge point
    page = (f"M{f(pg.x + 22)} {f(pg.y)}H{f(fx0)}L{f(fx1)} {f(fy1)}V{f(pg.b - 22)}Q{f(pg.r)} {f(pg.b)} "
            f"{f(pg.r - 22)} {f(pg.b)}H{f(pg.x + 22)}Q{f(pg.x)} {f(pg.b)} {f(pg.x)} {f(pg.b - 22)}"
            f"V{f(pg.y + 22)}Q{f(pg.x)} {f(pg.y)} {f(pg.x + 22)} {f(pg.y)}Z")
    with doc.g(clip=doc.clip_path(page)):
        doc.rect(pg.x, pg.y, pg.w, pg.h, "#FFFFFF")
        _form(doc, Box(pg.x + 30, pg.y, pg.w - 60, pg.h), button=p.accent)
    # shadow the page casts into the opening
    doc.path(f"M{f(fx0)} {f(fy0)}L{f(fx1)} {f(fy1)}", stroke="#000", sw=26, opacity=0.35,
             extra=f' filter="{doc.blur(12)}"')
    # the flap: the corner reflected over the fold line, its back lit, slightly curled
    ux, uy = fx1 - fx0, fy1 - fy0
    n2 = ux * ux + uy * uy
    cx, cy = pg.r, pg.y
    t = ((cx - fx0) * ux + (cy - fy0) * uy) / n2
    px, py = fx0 + t * ux, fy0 + t * uy
    rx, ry = 2 * px - cx, 2 * py - cy
    rx, ry = px + (rx - px) * 0.42, py + (ry - py) * 0.42
    flap = (f"M{f(fx0)} {f(fy0)}Q{f((fx0 + rx) / 2 + 26)} {f((fy0 + ry) / 2 - 18)} {f(rx)} {f(ry)}"
            f"Q{f((fx1 + rx) / 2 + 18)} {f((fy1 + ry) / 2 - 8)} {f(fx1)} {f(fy1)}Z")
    doc.path(flap, fill="#000", opacity=0.30, extra=f' transform="translate(-16 22)" filter="{doc.blur(16)}"')
    doc.path(flap, fill=doc.lin([(0, "#F7F9FB", 1), (0.55, "#E3EAF1", 1), (1, "#AEBBC9", 1)],
                                0.5, 0.5, 0, 1))
    doc.path(f"M{f(fx0)} {f(fy0)}L{f(fx1)} {f(fy1)}", stroke="#FFFFFF", sw=3, opacity=0.9)
    doc.focus = Box(210, 110, 1180, 664)
    vignette(doc, 0.35)


ALTERNATIVES: dict[str, Callable[[Doc, EditorialBrief, random.Random], None]] = {"a": _comp_copy, "b": _comp_peel}


@scene("payment_skimmer")
def payment_skimmer(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    _comp_peel(doc, brief, rng)
