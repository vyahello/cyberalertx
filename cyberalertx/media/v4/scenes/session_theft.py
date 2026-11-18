"""Session theft through a phishing kit (adversary-in-the-middle): the victim
signs in on a look-alike page, the kit relays the login to the real service
and keeps the session token, which is replayed from another browser.

Brand-neutral on purpose: a generic cloud-office sign-in, no vendor logo or
interface, `.example` domains only."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from ..kit import Box, Doc, arrow, background, icon, pill, vignette, window
from . import scene


def _field(doc: Doc, x: float, y: float, w: float, value: str, *, mono: bool = False, dots: int = 0,
           active: bool = False) -> None:
    p = doc.pal
    doc.rect(x, y, w, 54, "#FFFFFF", 8, stroke=p.accent if active else p.line, sw=2 if active else 1.4)
    if dots:
        for i in range(dots):
            doc.circle(x + 26 + i * 20, y + 27, 5.5, p.on_surface)
    else:
        doc.text(value, x + 18, y + 34, 19, p.on_surface, "mono" if mono else "ui")


def _signin(doc: Doc, b: Box) -> tuple[float, float]:
    """Generic sign-in card; returns the point where the submitted login leaves it."""
    p = doc.pal
    card = Box(b.cx - 230, b.y + 52, 460, 430)
    doc.shadow(card.x, card.y, card.w, card.h, 10, 0.6)
    doc.rect(card.x, card.y, card.w, card.h, "#FFFFFF", 10, stroke=p.line, sw=1)
    # neutral mark (not any vendor's logo)
    doc.circle(card.x + 52, card.y + 58, 16, p.accent)
    doc.circle(card.x + 52, card.y + 58, 7, "#FFFFFF")
    doc.text("Sign in", card.x + 36, card.y + 128, 34, p.on_surface, "display")
    doc.text("to continue to your work account", card.x + 38, card.y + 160, 17, p.muted, "ui")
    _field(doc, card.x + 36, card.y + 186, card.w - 72, "j.doe@company.example", mono=True)
    _field(doc, card.x + 36, card.y + 252, card.w - 72, "", dots=11, active=True)
    # MFA code already entered: the relay captures the session that follows it
    doc.text("Verification code", card.x + 38, card.y + 340, 16, p.muted, "ui")
    for i, d in enumerate("482913"):
        bx = card.x + 36 + i * 46
        doc.rect(bx, card.y + 352, 38, 46, "#F3F6F9", 6, stroke=p.line)
        doc.text(d, bx + 19, card.y + 383, 22, p.on_surface, "mono_bold", anchor="middle")
    doc.rect(card.r - 152, card.y + 352, 116, 46, p.accent, 6)
    doc.text("Sign in", card.r - 94, card.y + 382, 18, "#FFFFFF", "ui_bold", anchor="middle")
    return card.r, card.y + 270


@scene("session_theft")
def session_theft(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.3, 0.15))

    # ---- victim: look-alike sign-in (hero). TLS padlock shown: it does not help here.
    victim = Box(70, 120, 720, 640)
    body = window(doc, victim, url="signin-portal-auth.example/common/oauth2", lock=True, surface="#EEF2F6",
                  chrome="#E2E8EF", url_color=p.danger)
    out_x, out_y = _signin(doc, body)

    # ---- the kit: a relay that sits between the victim and the real service
    rx, ry = 975, 405
    doc.shadow(rx - 92, ry - 62, 184, 124, 16, 0.8)
    doc.rect(rx - 92, ry - 62, 184, 124, "#13202F", 16)
    for i in range(3):
        doc.rect(rx - 70, ry - 40 + i * 30, 140, 20, "#1F3247", 4)
        doc.circle(rx + 56, ry - 30 + i * 30, 4, p.danger if i == 1 else "#4ADE80")
    doc.text("phishing kit relay", rx, ry + 92, 17, p.on_surface, "mono_bold", anchor="middle")

    # ---- the real service, upstream (small, trustworthy, out of the victim's sight)
    real = Box(1200, 110, 340, 190)
    rb = window(doc, real, url="login.service.example", lock=True, surface="#FFFFFF", depth=0.6)
    icon(doc, "check", rb.cx - 60, rb.cy + 2, 40, p.safe, 3.5)
    doc.text("authenticated", rb.cx - 30, rb.cy + 10, 22, p.on_surface, "ui", anchor="start")

    # traffic: victim -> relay -> real service, and the response back
    arrow(doc, [(out_x + 14, ry - 18), (rx - 104, ry - 18)], p.on_surface, sw=3, head=14)
    arrow(doc, [(rx - 104, ry + 18), (out_x + 14, ry + 18)], p.muted, sw=2.5, head=12, dash="7 7")
    arrow(doc, [(rx + 40, ry - 70), (rx + 90, 230), (real.x - 14, 210)], p.on_surface, sw=3, head=14)

    # ---- the stolen session token
    tx, ty = 1040, 560
    tok = Box(tx, ty, 380, 74)
    doc.shadow(tok.x, tok.y, tok.w, tok.h, 12, 0.7)
    doc.rect(tok.x, tok.y, tok.w, tok.h, "#FFF4E8", 12, stroke=p.danger, sw=2.5)
    icon(doc, "cookie", tok.x + 40, tok.cy, 34, p.danger, 2.4)
    doc.text("session token", tok.x + 74, tok.y + 30, 15, p.danger, "ui_bold")
    doc.text("eyJ0eXAiOiJKV1QiLCJh…", tok.x + 74, tok.y + 56, 19, p.on_surface, "mono")
    arrow(doc, [(rx + 96, ry + 20), (rx + 190, ry + 40), (tx + 170, ty - 8)], p.danger, sw=4, head=17)

    # ---- replayed from the attacker's browser: an inbox opens without a password
    atk = Box(1080, 690, 400, 170)
    ab = window(doc, atk, url="mail.service.example/inbox", lock=True, surface="#FFFFFF", depth=0.7)
    for i in range(2):
        y = ab.y + 30 + i * 46
        doc.circle(ab.x + 34, y, 12, "#D7E2EE")
        doc.rect(ab.x + 58, y - 10, 150 + 40 * ((i + 1) % 2), 9, "#B7C6D6", 4)
        doc.rect(ab.x + 58, y + 5, 230, 7, "#DCE5EE", 3)
    arrow(doc, [(tok.x + 60, tok.b + 4), (tok.x + 60, atk.y - 14)], p.danger, sw=4, head=17)
    pill(doc, tok.x + 82, tok.b + 12, "replay", fg="#FFFFFF", bg=p.danger, size=15)

    vignette(doc, 0.3)
    doc.focus = Box(560, 150, 960, 540)          # relay, real service and the stolen token
