"""Compromised company websites used against their own visitors (watering
hole). The subject is the visitor's side: a familiar-looking corporate page
whose source now carries one injected script, which serves a wallet-draining
prompt to a desktop visitor and an exploit to a phone.

Site names appear only as plain-text tab titles, and only when the headline
names them (brief.entities); pages are generic, the phone has no logo."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from .. import type as T
from ..kit import Box, Doc, arrow, background, icon, pill, vignette, window
from . import scene

_ATTACK = ("exploited", "confirmed", "attacks_observed", "compromise")


def _tabs(doc: Doc, b: Box, names: list[str], active: int, light: bool = True) -> None:
    """Browser tab strip drawn into the window's title bar."""
    x = b.x + 92
    for i, n in enumerate(names):
        w = 196
        on = i == active
        if on:
            doc.add(f'<path d="M{x:.1f} {b.y + 38:.1f}V{b.y + 16:.1f}Q{x:.1f} {b.y + 8:.1f} {x + 8:.1f} '
                    f'{b.y + 8:.1f}H{x + w - 8:.1f}Q{x + w:.1f} {b.y + 8:.1f} {x + w:.1f} {b.y + 16:.1f}'
                    f'V{b.y + 38:.1f}Z" fill="{"#F4F6FA" if light else "#1C2740"}"/>')
        doc.circle(x + 20, b.y + 24, 6, "#9AA6B8" if not on else "#3B4A63")
        doc.text(T.fit(n, 15, w - 60, "ui"), x + 34, b.y + 29, 15, "#1B2433" if on and light else "#9AA6B8",
                 "ui")
        x += w + 4


def _corporate_page(doc: Doc, b: Box, rng: random.Random) -> None:
    ink, soft, mid = "#1B2433", "#D3DAE5", "#AEB8C8"
    doc.rect(b.x, b.y, b.w, 60, "#FFFFFF")
    doc.rect(b.x + 30, b.y + 20, 120, 20, ink, 4)
    for i in range(4):
        doc.rect(b.x + 330 + i * 110, b.y + 25, 74, 10, mid, 3)
    doc.rect(b.r - 150, b.y + 14, 120, 32, "#1B2433", 16)
    hero = Box(b.x, b.y + 60, b.w, b.h - 60)
    doc.rect(hero.x, hero.y, hero.w, hero.h, doc.lin([(0, "#E9EEF5", 1), (1, "#DCE3EE", 1)]))
    doc.rect(hero.x + 40, hero.y + 60, 380, 30, ink, 5)
    doc.rect(hero.x + 40, hero.y + 104, 300, 30, ink, 5)
    for i in range(3):
        doc.rect(hero.x + 40, hero.y + 162 + i * 22, 340 - i * 60, 10, mid, 3)
    doc.rect(hero.x + 40, hero.y + 250, 150, 44, "#2F6BFF", 8)
    # product shot
    doc.rect(hero.x + 500, hero.y + 50, 400, 260, "#C3CDDB", 10)
    doc.rect(hero.x + 530, hero.y + 80, 340, 200, "#AEB9CA", 6)


def _phone(doc: Doc, b: Box) -> Box:
    """A generic smartphone, three-quarter-flat elevation. Returns the screen box."""
    p = doc.pal
    doc.shadow(b.x, b.y, b.w, b.h, 54, 1.1)
    # side buttons
    doc.rect(b.x - 4, b.y + 150, 6, 60, "#3A4458", 3)
    doc.rect(b.x - 4, b.y + 228, 6, 60, "#3A4458", 3)
    doc.rect(b.r - 2, b.y + 190, 6, 90, "#3A4458", 3)
    doc.rect(b.x, b.y, b.w, b.h, doc.lin([(0, "#4B5568", 1), (0.5, "#2A3140", 1), (1, "#1A1F2A", 1)], 0, 0, 1, 1),
             54, stroke="#5D677B", sw=1.5)
    doc.rect(b.x + 6, b.y + 6, b.w - 12, b.h - 12, "#0A0D12", 49)
    s = Box(b.x + 16, b.y + 16, b.w - 32, b.h - 32)
    doc.rect(s.x, s.y, s.w, s.h, "#F4F6FA", 40)
    with doc.g(clip=doc.clip_rect(s.x, s.y, s.w, s.h, 40)):
        ink, soft, mid = "#1B2433", "#D3DAE5", "#AEB8C8"
        doc.rect(s.x, s.y, s.w, 90, "#FFFFFF")
        doc.rect(s.x + 24, s.y + 56, 80, 14, ink, 3)
        for i in range(3):
            doc.rect(s.r - 44, s.y + 54 + i * 7, 20, 3, ink, 1)
        doc.rect(s.x + 24, s.y + 120, s.w - 48, 24, ink, 4)
        doc.rect(s.x + 24, s.y + 154, s.w - 96, 24, ink, 4)
        for i in range(3):
            doc.rect(s.x + 24, s.y + 198 + i * 20, s.w - 60 - i * 40, 9, mid, 3)
        doc.rect(s.x + 24, s.y + 270, s.w - 48, 190, "#C3CDDB", 12)
        doc.rect(s.x + 24, s.y + 476, s.w - 48, 44, "#2F6BFF", 10)
        # address bar at the bottom of the screen
        doc.rect(s.x + 20, s.b - 64, s.w - 40, 40, "#E2E7EF", 20)
        icon(doc, "lock", s.x + 44, s.b - 44, 14, "#5B6B7D", 1.6)
        doc.rect(s.x + 60, s.b - 48, s.w - 120, 8, mid, 3)
        # glass highlight
        doc.path(f"M{s.x:.1f} {s.y:.1f}H{s.x + s.w * 0.7:.1f}L{s.x:.1f} {s.y + s.h * 0.45:.1f}Z", fill="#FFFFFF",
                 opacity=0.18)
    doc.circle(b.cx, b.y + 36, 9, "#0A0D12")                      # punch-hole camera
    doc.circle(b.cx + 2, b.y + 34, 3, "#2A3445")
    return s


@scene("compromised_sites")
def compromised_sites(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.4, 0.15))
    attack = brief.status in _ATTACK
    names = [e for e in brief.entities if e.isascii() and len(e) > 1][:3]
    if not names:
        names = ["Company site", "Company site"]
    filler = ["Home", "Products", "Support"]

    # ---- many affected sites: windows stacked behind the front one
    for k, (x, y) in enumerate(((150, 30), (100, 72))):
        bw = Box(x, y, 960, 600)
        window(doc, bw, title="", surface="#C9D1DD", chrome="#B9C3D1" if k == 0 else "#C7D0DC", depth=0.5)
        doc.rect(bw.x, bw.y, bw.w, bw.h, "#0A0F1A", 14, opacity=0.35 - k * 0.12)
        _tabs(doc, bw, [names[(k + 1) % len(names)], filler[k]], 0)

    # ---- the visited site on a desktop browser (hero)
    dw = Box(54, 118, 1010, 690)
    body = window(doc, dw, title="", surface="#F4F6FA", chrome="#DDE3EC")
    _tabs(doc, dw, [names[0], filler[2]], 0)
    page = Box(body.x, body.y, body.w, body.h - 120)
    with doc.g(clip=doc.clip_rect(page.x, page.y, page.w, page.h)):
        _corporate_page(doc, page, rng)

    # page source panel: the injected tag
    src = Box(body.x, body.b - 120, body.w, 120)
    doc.add(f'<path d="M{src.x:.1f} {src.y:.1f}H{src.r:.1f}V{src.b - 14:.1f}Q{src.r:.1f} {src.b:.1f} '
            f'{src.r - 14:.1f} {src.b:.1f}H{src.x + 14:.1f}Q{src.x:.1f} {src.b:.1f} {src.x:.1f} {src.b - 14:.1f}Z" '
            f'fill="#101725"/>')
    doc.text("Elements", src.x + 24, src.y + 28, 14, p.muted, "ui_bold")
    doc.text('<link rel="stylesheet" href="/assets/site.css">', src.x + 24, src.y + 58, 16, p.muted, "mono")
    tag_y = src.y + 92
    doc.rect(src.x + 12, tag_y - 22, 640, 32, p.danger, 4, opacity=0.18)
    doc.rect(src.x + 12, tag_y - 22, 4, 32, p.danger)
    doc.text('<script src="https://cdn-assets.example/c.js">', src.x + 24, tag_y, 16, "#FFB4AD", "mono")
    pill(doc, src.x + 664, tag_y - 21, "injected", fg="#FFFFFF", bg=p.danger, size=13, font="ui_bold")

    # ---- the phone visitor
    ph = Box(1196, 150, 318, 640)
    if attack:
        doc.glow(ph.cx, ph.cy, ph.w * 0.75, ph.h * 0.55, p.danger, 0.16)
    _phone(doc, ph)

    if attack:
        # desktop: wallet-draining prompt over the page
        m = Box(page.x + 300, page.y + 96, 420, 330)
        doc.rect(page.x, page.y, page.w, page.h, "#0A0F1A", opacity=0.45)
        doc.shadow(m.x, m.y, m.w, m.h, 14, 1.0)
        doc.rect(m.x, m.y, m.w, m.h, "#FFFFFF", 14, stroke=p.danger, sw=2.5)
        doc.text("Connect wallet", m.x + 30, m.y + 56, 28, "#111827", "display")
        doc.text("to claim your reward", m.x + 30, m.y + 86, 16, "#6B7280", "ui")
        for i, label in enumerate(("Browser extension wallet", "Mobile wallet")):
            ry = m.y + 110 + i * 62
            doc.rect(m.x + 30, ry, m.w - 60, 50, "#F3F5F8", 8, stroke="#DDE2EA")
            icon(doc, "key", m.x + 56, ry + 25, 22, "#374151", 2)
            doc.text(label, m.x + 82, ry + 31, 17, "#111827", "ui")
        doc.rect(m.x + 30, m.y + 244, m.w - 60, 52, p.danger, 8)
        doc.text("Approve all assets", m.cx, m.y + 277, 19, "#FFFFFF", "ui_bold", anchor="middle")

        # one script, two payloads
        sx, sy = src.x + 600, tag_y - 26
        arrow(doc, [(sx, sy), (sx, m.b + 14)], p.danger, sw=4, head=16)
        pill(doc, sx, (sy + m.b) / 2 - 15, "wallet drainer", fg="#FFFFFF", bg=p.danger, size=15, anchor="middle")
        ay = ph.y + 380
        arrow(doc, [(src.x + 760, tag_y - 6), (1130, tag_y - 6), (1130, ay), (ph.x - 14, ay)], p.danger,
              sw=4, head=16, smooth=False)
        pill(doc, 950, tag_y - 21, "iPhone exploit", fg="#FFFFFF", bg=p.danger, size=15,
             anchor="middle")
    vignette(doc, 0.45)
    doc.focus = Box(330, 160, 1180, 664)
