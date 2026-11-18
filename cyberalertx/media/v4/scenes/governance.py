"""Cyber risk as a management topic (analysis, no incident): a printed
planning briefing on the table — a likelihood x impact risk matrix and a
responsibility grid that spreads ownership beyond the IT department.

Nothing here is a figure from the sources: the matrix positions and the grid
are a generic planning layout, which is what these columns discuss."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, vignette
from . import scene

#: Accountable / Responsible / Consulted / Informed: the board owns the risk,
#: IT and operations carry it out, the rest are involved.
_GRID = (("Board", "A"), ("Finance", "C"), ("Legal", "C"), ("HR", "I"), ("Operations", "R"), ("IT", "R"))


def _matrix(doc: Doc, x: float, y: float, cell: float, rng: random.Random) -> tuple[float, float]:
    """5x5 likelihood x impact grid; returns the centre of the top risk."""
    p = doc.pal
    heat = ("#E7EFE3", "#F3EBCB", "#F6D9B5", "#F2B9A4", "#E58A7A")
    for r in range(5):
        for c in range(5):
            level = min(4, (4 - r) + c) // 2 + (1 if (4 - r) + c >= 6 else 0)
            doc.rect(x + c * cell, y + r * cell, cell - 4, cell - 4, heat[min(level, 4)], 4)
    doc.text("impact", x + 2.5 * cell, y + 5 * cell + 30, 17, p.muted, "ui_bold", anchor="middle", tracking=2)
    with doc.g(transform=f"rotate(-90 {f(x - 22)} {f(y + 2.5 * cell)})"):
        doc.text("likelihood", x - 22, y + 2.5 * cell, 17, p.muted, "ui_bold", anchor="middle", tracking=2)
    cells = [(r, c) for r in range(4) for c in range(1, 5) if (r, c) != (0, 4)]
    rng.shuffle(cells)
    risks = [(0, 4), *cells[:4]]                          # the risk the briefing is about: likely, severe
    top = (0.0, 0.0)
    for i, (r, c) in enumerate(risks):
        cx, cy = x + c * cell + cell / 2 - 2, y + r * cell + cell / 2 - 2
        if i == 0:
            top = (cx, cy)
            doc.circle(cx, cy, 20, p.danger, opacity=0.18)
            doc.circle(cx, cy, 11, p.danger)
        else:
            doc.circle(cx, cy, 8, p.ink, opacity=0.75)
    return top


@scene("governance")
def governance(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.4, 0.15))
    # ---- the briefing, slightly turned on the table
    sheet = Box(150, 70, 1020, 900)
    with doc.g(transform=f"rotate({rng.uniform(-2.4, -1.2):.2f} 660 500)"):
        doc.shadow(sheet.x, sheet.y, sheet.w, sheet.h, 4, 1.2)
        doc.rect(sheet.x, sheet.y, sheet.w, sheet.h, "#FBF9F4", 4)
        doc.rect(sheet.x, sheet.y, sheet.w, 10, p.accent)
        doc.text("CYBER RISK", sheet.x + 70, sheet.y + 92, 22, p.muted, "ui_bold", tracking=5)
        doc.text("Planning briefing", sheet.x + 70, sheet.y + 160, 58, p.ink, "display")
        doc.line((sheet.x + 70, sheet.y + 196), (sheet.r - 70, sheet.y + 196), p.ink, 3)
        top = _matrix(doc, sheet.x + 120, sheet.y + 250, 82, rng)
        # responsibility grid: ownership spread across the organisation
        gx, gy = sheet.x + 600, sheet.y + 262
        doc.text("who owns it", gx, gy - 22, 17, p.muted, "ui_bold", tracking=2)
        for i, (d, role) in enumerate(_GRID):
            y = gy + i * 62
            doc.rect(gx, y, 340, 50, "#F1ECE2" if i % 2 == 0 else "#FBF9F4", 4)
            doc.text(d, gx + 18, y + 33, 22, p.ink, "ui")
            col = p.accent if role in ("A", "R") else p.muted
            doc.rect(gx + 270, y + 9, 52, 32, col, 6, opacity=1 if role in ("A", "R") else 0.25)
            doc.text(role, gx + 296, y + 32, 20, "#FFFFFF" if role in ("A", "R") else p.ink, "mono_bold",
                     anchor="middle")
        # the top risk is owned at board level, not only by IT
        doc.path(f"M{f(top[0] + 22)} {f(top[1])}L{f(gx - 10)} {f(gy + 25)}", stroke=p.danger, sw=3, dash="2 8")
        for i in range(4):
            doc.rect(sheet.x + 70, sheet.y + 740 + i * 28, 820 - 140 * (i % 3), 9, "#E2DACB", 4)
    # ---- a pen on the table, for scale and the hand-made feel of planning
    with doc.g(transform="rotate(-28 1340 640)"):
        doc.shadow(1180, 625, 340, 26, 13, 0.5)
        doc.rect(1180, 625, 300, 26, doc.lin([(0, "#2B3240", 1), (1, "#11151C", 1)]), 13)
        doc.rect(1470, 628, 44, 20, "#C9A86A", 6)
        doc.poly([(1180, 630), (1150, 638), (1180, 646)], "#C9A86A")
    doc.focus = Box(180, 150, 1100, 619)
    vignette(doc, 0.3)
