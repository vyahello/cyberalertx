"""Disclosure policy: a bug report on a timeline whose fix deadline moves
earlier. The report card (bug-tracker style) sits at day zero; the old
deadline is a ghosted flag far right, the new one a solid flag closer in, and
the time vendors lose is hatched between them. Day counts appear only when
`brief.facts` states them."""
from __future__ import annotations

import random

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, arrow, background, f, icon, pill, vignette
from . import scene
from ._editorial import grid, hatch


def _flag(doc: Doc, x: float, base: float, h: float, col: str, label: str, *, ghost: bool = False) -> None:
    """A deadline flag planted on the axis."""
    p = doc.pal
    w = T.measure(label, 22, "ui_bold", 1.5) + 70
    if ghost:
        doc.line((x, base), (x, base - h), col, 3, dash="6 7")
        doc.path(f"M{f(x)} {f(base - h)}h{f(w)}l-28 38l28 38h-{f(w)}z", fill="none", stroke=col, sw=2.5,
                 dash="7 6")
        doc.text(label, x + 18, base - h + 46, 22, col, "ui_bold", tracking=1.5)
        return
    doc.line((x, base), (x, base - h), p.ink, 4)
    doc.path(f"M{f(x)} {f(base - h)}h{f(w)}l-28 38l28 38h-{f(w)}z", fill=col)
    doc.text(label, x + 18, base - h + 46, 22, "#FFFFFF", "ui_bold", tracking=1.5)
    doc.circle(x, base, 9, p.ink)


@scene("disclosure_deadline")
def disclosure_deadline(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.3, 0.15))
    grid(doc, 40, 0.3)
    days = brief.facts.get("days")
    base = 660.0
    x_rep, x_new, x_old = 190.0, 860.0, 1280.0

    # ---- the time axis: a ruler with unlabelled ticks (no invented counts)
    doc.rect(120, base - 3, 1380, 6, p.ink, 3)
    for i in range(0, 69):
        x = 130 + i * 20
        if x > 1490:
            break
        doc.line((x, base + 6), (x, base + (22 if i % 5 == 0 else 13)), p.ink, 1.5, 0.55)
    # fix window that remains, and the part that was cut
    doc.rect(x_rep, base - 70, x_new - x_rep, 52, p.accent, 6, opacity=0.14)
    doc.rect(x_rep, base - 70, x_new - x_rep, 52, "none", 6, stroke=p.accent, sw=2)
    doc.text("fix window", x_rep + 22, base - 36, 22, p.accent, "ui_bold")
    hatch(doc, x_new, base - 70, x_old - x_new, 52, p.danger, gap=14, sw=2, opacity=0.45)
    doc.rect(x_new, base - 70, x_old - x_new, 52, "none", 0, stroke=p.danger, sw=1.5, opacity=0.5)

    # ---- flags
    _flag(doc, x_old, base, 400, p.muted, "OLD DEADLINE", ghost=True)
    _flag(doc, x_new, base, 400, p.danger, "NEW DEADLINE")
    arrow(doc, [(x_old - 14, base - 130), (x_new + 22, base - 130)], p.danger, sw=5, head=22)
    doc.circle(x_old, base - 130, 7, p.muted)
    if days:
        pill(doc, x_new + 8, base + 40, f"{days} days", fg="#FFFFFF", bg=p.danger, size=20, font="mono_bold")

    # labels under the axis
    doc.text("reported", x_rep, base + 62, 22, p.ink, "ui_bold", anchor="middle")
    doc.text("public", x_new, base + 62 + (40 if days else 0), 22, p.ink, "ui_bold", anchor="middle")
    icon(doc, "globe", x_new, base + 100 + (40 if days else 0), 28, p.ink, 2)
    doc.text("public", x_old, base + 62, 22, p.muted, "ui", anchor="middle")

    # ---- the bug report at day zero (tracker card)
    card = Box(110, 120, 560, 300)
    doc.shadow(card.x, card.y, card.w, card.h, 10, 0.8)
    doc.rect(card.x, card.y, card.w, card.h, "#FFFFFF", 10, stroke=p.line, sw=1.2)
    doc.rect(card.x, card.y, card.w, 58, "#F3EFE7", 10)
    doc.rect(card.x, card.y + 48, card.w, 10, "#F3EFE7")
    doc.line((card.x, card.y + 58), (card.r, card.y + 58), p.line, 1)
    issue = "".join(rng.choice("0123456789") for _ in range(9))
    doc.text(f"Issue {issue}", card.x + 26, card.y + 38, 20, p.on_surface, "mono_bold")
    pill(doc, card.r - 24, card.y + 13, "restricted", fg=p.on_surface, bg="#E6DFD2", size=15, anchor="end")
    icon(doc, "warn", card.x + 44, card.y + 108, 34, p.danger, 2.4)
    doc.text("Security bug", card.x + 80, card.y + 118, 32, p.on_surface, "display")
    rows = (("vendor", "notified"), ("status", "awaiting fix"), ("disclosure", "on deadline"))
    for i, (k, v) in enumerate(rows):
        y = card.y + 180 + i * 44
        doc.text(k, card.x + 30, y, 19, p.muted, "mono")
        doc.text(v, card.x + 200, y, 19, p.danger if k == "disclosure" else p.on_surface, "mono_bold")
    # leader from the card to day zero
    doc.line((x_rep, card.b), (x_rep, base - 70), p.ink, 2, dash="3 6")
    doc.circle(x_rep, base, 10, p.accent)
    doc.circle(x_rep, base, 4, "#FFFFFF")
    doc.focus = Box(100, 100, 1420, 799)
    vignette(doc, 0.3)
