"""Self-hosted versus SaaS (analysis, no incident): the company's own server
cabinet on the left, a SaaS subscription on the right, and between them a
ledger of who controls what — data location, updates, backups, access and
uptime. Self-hosted puts every row on the company's side; with SaaS most rows
move to the vendor, access management stays with the customer."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from ..kit import Box, Doc, background, vignette, window
from . import scene
from ._editorial import grid, rack_unit

_ROWS = (("data location", "you", "vendor"), ("updates", "you", "vendor"), ("backups", "you", "vendor"),
         ("user access", "you", "you"), ("uptime", "you", "vendor"))


def _cabinet(doc: Doc, x: float, y: float, w: float, h: float, rng: random.Random) -> None:
    """A floor-standing server cabinet, front elevation, door open."""
    doc.add(f'<ellipse cx="{x + w / 2}" cy="{y + h + 6}" rx="{w * 0.6}" ry="12" fill="#000" opacity="0.25" '
            f'filter="{doc.blur(8)}"/>')
    doc.rect(x, y, w, h, doc.lin([(0, "#2A2E35", 1), (1, "#181B20", 1)], 0, 0, 1, 0), 8)
    doc.rect(x + 6, y + 6, w - 12, 26, "#14171B", 4)
    for i in range(int((w - 40) // 14)):
        doc.rect(x + 20 + i * 14, y + 13, 8, 12, "#2E333A", 2)
    ix, iy, iw = x + 22, y + 44, w - 44
    doc.rect(ix - 8, iy - 4, iw + 16, h - 92, "#0D0F12", 4)
    kinds = ["switch", "switch", "server", "server", "server", "storage", "server", "storage", "server"]
    yy = iy + 4
    for k, kind in enumerate(kinds):
        uh = 34 if kind == "switch" else 52
        if yy + uh > y + h - 56:
            break
        rack_unit(doc, ix, yy, iw, uh, kind=kind, rng_bits=k + rng.randrange(3))
        yy += uh + 6
    doc.rect(x + 14, y + h - 42, w - 28, 28, "#14171B", 4)
    for fx in (x + 18, x + w - 42):
        doc.rect(fx, y + h, 24, 10, "#0E1013", 2)
    # open glass door, seen edge-on at the left
    doc.poly([(x - 34, y + 20), (x, y), (x, y + h), (x - 34, y + h - 20)], "#9FB3C8", opacity=0.25)
    doc.path(f"M{x - 34} {y + 20}L{x} {y}V{y + h}L{x - 34} {y + h - 20}Z", stroke="#5C6B7A", sw=2)


def _saas(doc: Doc, b: Box) -> Box:
    p = doc.pal
    body = window(doc, b, url="app.vendor.example/billing", lock=True, surface="#FFFFFF", chrome="#F1ECE3")
    x = body.x + 32
    doc.text("Subscription", x, body.y + 58, 30, p.on_surface, "display")
    card = Box(x, body.y + 86, body.w - 64, 150)
    doc.rect(card.x, card.y, card.w, card.h, "#F6F3EC", 10, stroke=p.line, sw=1.2)
    doc.text("Business plan", card.x + 22, card.y + 42, 22, p.on_surface, "ui_bold")
    doc.text("per user / month", card.x + 22, card.y + 72, 18, p.muted, "ui")
    doc.rect(card.x + 22, card.y + 98, card.w - 44, 12, "#E3DDD0", 6)
    doc.rect(card.x + 22, card.y + 98, (card.w - 44) * 0.64, 12, p.accent, 6)
    doc.text("seats", card.x + 22, card.y + 136, 15, p.muted, "ui_bold")
    rows = (("hosting", "vendor cloud"), ("region", "set by vendor"), ("renewal", "monthly"))
    for i, (k, v) in enumerate(rows):
        yy = card.b + 46 + i * 40
        doc.text(k, x, yy, 18, p.muted, "mono")
        doc.text(v, x + 140, yy, 18, p.on_surface, "mono_bold")
    doc.rect(x, body.b - 74, body.w - 64, 46, p.accent, 8)
    doc.text("Manage plan", x + (body.w - 64) / 2, body.b - 44, 19, "#FFFFFF", "ui_bold", anchor="middle")
    return body


def _who(doc: Doc, cx: float, y: float, who: str) -> None:
    p = doc.pal
    w = 116
    if who == "you":
        doc.rect(cx - w / 2, y - 20, w, 40, p.ink, 20)
        doc.text("you", cx, y + 7, 19, "#FBF8F2", "ui_bold", anchor="middle")
    else:
        doc.rect(cx - w / 2, y - 20, w, 40, "none", 20, stroke=p.muted, sw=2)
        doc.text("vendor", cx, y + 7, 19, p.muted, "ui_bold", anchor="middle")


@scene("selfhosted_saas")
def selfhosted_saas(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.5, 0.1))
    grid(doc, 40, 0.25)
    # split: left half slightly warmer, right half cooler
    doc.rect(800, 0, 800, 900, "#D9DEE2", opacity=0.35)
    doc.line((800, 60), (800, 170), p.ink, 1.5, 0.35)
    doc.line((800, 740), (800, 840), p.ink, 1.5, 0.35)

    doc.text("SELF-HOSTED", 70, 98, 40, p.ink, "display", tracking=1)
    doc.text("SaaS", 1530, 98, 40, p.ink, "display", anchor="end", tracking=1)

    _cabinet(doc, 110, 150, 300, 650, rng)
    _saas(doc, Box(1150, 170, 390, 590))

    # ---- the control ledger
    lx, rx, cx = 545, 1055, 800
    doc.text("WHO CONTROLS", cx, 210, 17, p.muted, "ui_bold", anchor="middle", tracking=3)
    for i, (label, left, right) in enumerate(_ROWS):
        y = 290 + i * 100
        doc.line((lx + 70, y), (rx - 70, y), p.line, 1.5)
        doc.rect(cx - 112, y - 22, 224, 44, "#F4EFE6", 22)
        doc.text(label, cx, y + 7, 21, p.on_surface, "ui_bold", anchor="middle")
        _who(doc, lx, y, left)
        _who(doc, rx, y, right)
    doc.focus = Box(60, 60, 1480, 832)
    vignette(doc, 0.25)
