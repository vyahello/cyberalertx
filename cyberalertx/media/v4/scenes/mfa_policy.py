"""Password and MFA requirements (guidance, no incident): a sign-in form with
the password policy it is checked against, and the second factor arriving
as an approval request on a phone. When the story names a policy framework
(e.g. CJIS) the policy document sits behind the form; when the story is about
a default password, the same form shows the failing checks instead."""
from __future__ import annotations

import random
import re

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, arrow, background, icon, vignette, window
from . import scene
from ._editorial import grid, phone


def _field(doc: Doc, x: float, y: float, w: float, label: str, value: str, *, dots: int = 0, col: str = "",
           active: bool = False) -> None:
    p = doc.pal
    doc.text(label, x, y - 12, 16, p.muted, "ui_bold", tracking=1)
    doc.rect(x, y, w, 52, "#FFFFFF", 8, stroke=col or (p.accent if active else p.line), sw=2.2 if (col or active)
             else 1.4)
    if dots:
        for i in range(dots):
            doc.circle(x + 24 + i * 19, y + 26, 5.5, p.on_surface)
    else:
        doc.text(value, x + 18, y + 34, 20, col or p.on_surface, "mono")


@scene("mfa_policy")
def mfa_policy(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.4, 0.15))
    grid(doc, 40, 0.28)
    t = brief.text
    default_pw = bool(re.search(r"default .{0,12}password|admin:admin|blank password", t))
    framework = next((e for e in brief.entities if e in ("CJIS", "NIST", "PCI", "HIPAA", "NIS2")), "")

    # ---- policy document behind the form
    if framework:
        dx, dy = 70, 70
        with doc.g(transform=f"rotate(-4 {dx + 200} {dy + 300})"):
            doc.shadow(dx, dy, 400, 560, 4, 0.6)
            doc.rect(dx, dy, 400, 560, "#FBF8F2", 4)
            doc.rect(dx, dy, 400, 10, p.accent)
            doc.text(framework, dx + 36, dy + 96, 64, p.on_surface, "display")
            doc.text("Security Policy", dx + 40, dy + 134, 22, p.muted, "ui")
            for i in range(8):
                y = dy + 190 + i * 40
                if framework == "CJIS":     # 5.6: identification and authentication policy area
                    doc.text(f"5.6.{i + 1}", dx + 40, y + 6, 16, p.muted, "mono")
                doc.rect(dx + 110, y - 4, 230 - (i * 37) % 90, 9, "#D9D1C2", 4)

    # ---- sign-in form with its policy checklist
    ox = 0 if framework else 150          # centre the pair when there is no policy document
    win = Box(380 - ox, 120, 640, 690)
    body = window(doc, win, url="portal.agency.example/sign-in", lock=True, surface="#F6F3EC", chrome="#ECE6DA")
    card = Box(body.x + 50, body.y + 36, body.w - 100, 300)
    doc.text("Sign in", card.x, card.y + 40, 38, p.on_surface, "display")
    user = "admin" if default_pw else "j.doe@agency.example"
    _field(doc, card.x, card.y + 92, card.w, "USERNAME", user)
    if default_pw:
        _field(doc, card.x, card.y + 182, card.w, "PASSWORD", "admin", col=p.danger)
    else:
        _field(doc, card.x, card.y + 182, card.w, "PASSWORD", "", dots=14, active=True)
    btn = Box(card.r - 150, card.y + 252, 150, 50)
    doc.rect(btn.x, btn.y, btn.w, btn.h, p.accent, 8)
    doc.text("Continue", btn.cx, btn.y + 32, 19, "#FFFFFF", "ui_bold", anchor="middle")

    # checklist
    cy0 = card.y + 336
    doc.rect(card.x - 18, cy0 - 14, card.w + 36, 278, "#FFFFFF", 10, stroke=p.line, sw=1.2)
    doc.text("PASSWORD POLICY", card.x, cy0 + 22, 15, p.muted, "ui_bold", tracking=2.5)
    if default_pw:
        checks = [("default credentials changed", False), ("strong password", False),
                  ("second factor required", False)]
    else:
        checks = [("minimum length", True), ("not on breached-password list", True),
                  ("MFA: privileged accounts", True), ("MFA: standard accounts", True)]
        if "privileged" not in t:
            checks[2:] = [("second factor required", True)]
    for i, (lab, ok) in enumerate(checks):
        ry = cy0 + 66 + i * 50
        col = p.safe if ok else p.danger
        doc.circle(card.x + 14, ry - 7, 14, col, opacity=0.14)
        icon(doc, "check" if ok else "cross", card.x + 14, ry - 7, 18, col, 2.8)
        doc.text(T.fit(lab, 21, card.w - 60, "ui"), card.x + 44, ry, 21, p.on_surface, "ui")

    # ---- the second factor on a phone
    px, py, pw, ph = 1140 - ox, 150, 300, 620
    sx, sy, sw, sh = phone(doc, px, py, pw, ph, body="#1B1D22", screen="#F4F6F9")
    doc.text("Sign-in request", sx + sw / 2, sy + 120, 24, p.on_surface, "ui_bold", anchor="middle")
    doc.circle(sx + sw / 2, sy + 210, 46, p.accent if not default_pw else "#D7DCE3", opacity=0.14 if not default_pw
               else 1)
    icon(doc, "key" if not default_pw else "cross", sx + sw / 2, sy + 210, 54,
         p.accent if not default_pw else p.danger, 2.6)
    doc.text("portal.agency.example", sx + sw / 2, sy + 296, 16, p.muted, "mono", anchor="middle")
    if default_pw:
        doc.text("no prompt sent", sx + sw / 2, sy + 340, 20, p.danger, "ui_bold", anchor="middle")
    else:
        doc.text("Is this you?", sx + sw / 2, sy + 340, 20, p.on_surface, "ui", anchor="middle")
    bw = sw - 56
    doc.rect(sx + 28, sy + sh - 190, bw, 54, "#FFFFFF", 27, stroke=p.line, sw=1.4)
    doc.text("Deny", sx + sw / 2, sy + sh - 155, 20, p.on_surface, "ui_bold", anchor="middle")
    approve = Box(sx + 28, sy + sh - 120, bw, 54)
    doc.rect(approve.x, approve.y, approve.w, approve.h, p.accent if not default_pw else "#C9CFD8", 27)
    doc.text("Approve", approve.cx, approve.y + 35, 20, "#FFFFFF", "ui_bold", anchor="middle")
    # push from the form to the phone
    arrow(doc, [(btn.r + 16, btn.cy), (1085 - ox, btn.cy), (1085 - ox, sy + 210), (px - 18, sy + 210)],
          p.accent if not default_pw else p.muted, sw=3, head=14, dash="" if not default_pw else "8 8")
    doc.focus = Box(330 - ox, 100, 1180, 664)
    vignette(doc, 0.3)
