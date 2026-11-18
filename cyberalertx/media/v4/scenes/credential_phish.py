"""Credential phishing: a lure email sends the reader to a look-alike sign-in
page, whose domain differs from the real one by a glyph (a loupe shows the
"rn" posing as "m"), and the password typed there lands in the attacker's
capture log. When the sources report a takedown or seizure, the log carries
the seizure stamp.

Different from `session_theft` on purpose: no relay and no session token;
the subject here is the lure and the stolen password itself."""
from __future__ import annotations

import random
import re

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, arrow, background, f, icon
from . import scene


def _step(doc: Doc, x: float, y: float, n: int, color: str) -> None:
    doc.circle(x, y, 19, color)
    doc.text(str(n), x, y + 7, 20, "#FFFFFF", "ui_bold", anchor="middle")


def _email(doc: Doc, b: Box, danger: str) -> tuple[float, float]:
    """Lure email in a reading pane. Returns the link button's centre."""
    p = doc.pal
    doc.shadow(b.x, b.y, b.w, b.h, 12, 0.9)
    doc.rect(b.x, b.y, b.w, b.h, "#FFFFFF", 12, stroke=p.line)
    doc.rect(b.x, b.y, b.w, 52, "#EDF2F6", 12)
    doc.rect(b.x, b.y + 40, b.w, 12, "#EDF2F6")
    icon(doc, "mail", b.x + 32, b.y + 26, 22, p.muted, 2)
    doc.text("Inbox", b.x + 54, b.y + 33, 16, p.muted, "ui_bold")
    x0 = b.x + 32
    doc.text("IT Service Desk", x0 + 60, b.y + 98, 19, p.on_surface, "ui_bold")
    doc.text("<it-support@acrne-helpdesk.example>", x0 + 60, b.y + 122, 14, p.muted, "mono")
    doc.circle(x0 + 22, b.y + 106, 22, "#D7E2EE")
    doc.text("IT", x0 + 22, b.y + 113, 16, p.on_surface, "ui_bold", anchor="middle")
    doc.text("Your password expires today", x0, b.y + 176, 26, p.on_surface, "display")
    for k, w in enumerate((0.92, 0.84, 0.6)):
        doc.rect(x0, b.y + 202 + k * 22, (b.w - 64) * w, 9, "#DCE4EC", 4)
    bx, by = x0, b.y + 290
    doc.rect(bx, by, 260, 50, p.accent, 8)
    doc.text("Keep current password", bx + 130, by + 32, 17, "#FFFFFF", "ui_bold", anchor="middle")
    # pointer on the button
    px, py = bx + 210, by + 34
    doc.path(f"M{f(px)} {f(py)}l0 30l8-7l6 13l6-3l-6-13l11-1z", fill="#FFFFFF", stroke="#0F1B2A", sw=2)
    return bx + 260, by + 25


def _loupe(doc: Doc, cx: float, cy: float, r: float, danger: str) -> None:
    """A magnifier over the address bar: the look-alike glyphs, enlarged."""
    p = doc.pal
    a = 0.785
    hx, hy = cx + r * 0.72, cy - r * 0.72
    doc.path(f"M{f(hx)} {f(hy)}L{f(hx + 70)} {f(hy - 70)}", stroke="#24323F", sw=20)
    doc.path(f"M{f(hx + 4)} {f(hy - 4)}L{f(hx + 22)} {f(hy - 22)}", stroke="#5B6B7D", sw=22, cap="butt")
    doc.add(f'<circle cx="{f(cx + 6)}" cy="{f(cy + 10)}" r="{f(r)}" fill="#000" opacity="0.18" '
            f'filter="{doc.blur(8)}"/>')
    doc.circle(cx, cy, r, "#FFFFFF")
    with doc.g(clip=doc.clip_path(f"M{f(cx - r)} {f(cy)}a{f(r)} {f(r)} 0 1 0 {f(2 * r)} 0a{f(r)} {f(r)} 0 1 0 "
                                  f"{f(-2 * r)} 0Z")):
        size = r * 0.62
        word = "acrne"
        w = T.measure(word, size, "mono")
        x0 = cx - w / 2
        doc.text("ac", x0, cy + size * 0.36, size, p.on_surface, "mono")
        rx = x0 + T.measure("ac", size, "mono")
        rw = T.measure("rn", size, "mono")
        doc.rect(rx - 4, cy - size * 0.55, rw + 8, size * 1.1, danger, 6, opacity=0.14)
        doc.text("rn", rx, cy + size * 0.36, size, danger, "mono_bold")
        doc.text("e", rx + rw, cy + size * 0.36, size, p.on_surface, "mono")
        doc.text("not \"m\"", cx, cy + r * 0.66, r * 0.17, danger, "ui_bold", anchor="middle")
    doc.circle(cx, cy, r, "none", "#24323F", 9)
    doc.circle(cx, cy, r - 6, "none", "#FFFFFF", 2, opacity=0.6)
    _ = a


@scene("credential_phish")
def credential_phish(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    background(doc, light=(0.25, 0.2))
    seized = re.search(r"takes? down|takedown|seiz|dismantl|ліквід|вилуч", text) is not None

    # ---- 1. the lure (back, upper left)
    em = Box(60, 120, 560, 380)
    with doc.g(f"rotate(-2 {f(em.cx)} {f(em.cy)})"):
        link = _email(doc, em, p.danger)
    _step(doc, em.x + 4, em.y + 2, 1, p.on_surface)

    # ---- 2. the look-alike sign-in page (centre, in front)
    br = Box(440, 330, 660, 500)
    doc.shadow(br.x, br.y, br.w, br.h, 14, 1.1)
    doc.rect(br.x, br.y, br.w, br.h, "#F8FAFC", 14, stroke=p.line, sw=1.2)
    doc.rect(br.x, br.y, br.w, 54, "#E3EAF1", 14)
    doc.rect(br.x, br.y + 40, br.w, 14, "#E3EAF1")
    for i, c in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
        doc.circle(br.x + 22 + i * 18, br.y + 27, 5.5, c, opacity=0.85)
    ub = Box(br.x + 86, br.y + 10, br.w - 110, 34)
    doc.rect(ub.x, ub.y, ub.w, ub.h, "#FFFFFF", 8, stroke=p.line)
    icon(doc, "lock", ub.x + 18, ub.cy, 15, p.safe, 2)
    url_x = ub.x + 36
    doc.text("login.", url_x, ub.cy + 6, 17, p.on_surface, "mono")
    ax = url_x + T.measure("login.", 17, "mono")
    doc.text("acrne", ax, ub.cy + 6, 17, p.danger, "mono_bold")
    doc.text(".example/signin", ax + T.measure("acrne", 17, "mono_bold"), ub.cy + 6, 17, p.on_surface, "mono")
    _step(doc, br.x + 4, br.y + 2, 2, p.on_surface)
    # the form: a copy of the real page
    fx = br.x + 150
    doc.rect(fx - 10, br.y + 92, 26, 26, p.accent, 5)
    doc.rect(fx + 20, br.y + 92, 26, 26, p.accent, 5, opacity=0.55)
    doc.text("Sign in", fx - 10, br.y + 170, 34, p.on_surface, "display")
    doc.rect(fx - 10, br.y + 196, 360, 52, "#FFFFFF", 8, stroke=p.line, sw=1.4)
    doc.text("j.doe@acme.example", fx + 8, br.y + 229, 18, p.on_surface, "mono")
    doc.rect(fx - 10, br.y + 264, 360, 52, "#FFFFFF", 8, stroke=p.danger, sw=2.2)
    for k in range(10):
        doc.circle(fx + 14 + k * 18, br.y + 290, 5, p.on_surface)
    doc.rect(fx + 14 + 10 * 18, br.y + 278, 2, 24, p.on_surface)
    doc.rect(fx - 10, br.y + 340, 360, 50, p.accent, 8)
    doc.text("Next", fx + 170, br.y + 371, 18, "#FFFFFF", "ui_bold", anchor="middle")
    lcx, lcy, lr = br.x + 400, br.y - 110, 92
    aw = T.measure("acrne", 17, "mono_bold")
    doc.path(f"M{f(ax)} {f(ub.y + 4)}L{f(lcx - lr * 0.8)} {f(lcy + lr * 0.6)}M{f(ax + aw)} {f(ub.y + 4)}"
             f"L{f(lcx + lr * 0.8)} {f(lcy + lr * 0.6)}", stroke=p.danger, sw=1.5, opacity=0.6)
    doc.rect(ax - 3, ub.y + 6, aw + 6, ub.h - 12, "none", 4, stroke=p.danger, sw=1.5)
    _loupe(doc, lcx, lcy, lr, p.danger)

    # lure -> page
    arrow(doc, [(link[0] + 8, link[1]), (ub.x - 40, link[1]), (ub.x - 40, ub.cy), (ub.x - 8, ub.cy)],
          p.on_surface, sw=2.5, head=12, dash="7 7")

    # ---- 3. the attacker's capture log (right)
    lg = Box(1160, 300, 400, 420)
    doc.shadow(lg.x, lg.y, lg.w, lg.h, 12, 1.0)
    doc.rect(lg.x, lg.y, lg.w, lg.h, "#0F1B2A", 12)
    doc.rect(lg.x, lg.y, lg.w, 44, "#172638", 12)
    doc.rect(lg.x, lg.y + 32, lg.w, 12, "#172638")
    doc.text("creds.log", lg.x + 20, lg.y + 29, 16, "#A9B6C6", "mono_bold")
    _step(doc, lg.x + 4, lg.y + 2, 3, p.on_surface)
    users = ("a.kim", "m.ortiz", "s.lee", "r.patel", "t.nowak", "e.berg")
    for k, u in enumerate(users):
        yy = lg.y + 82 + k * 40
        doc.text(f"{u}@", lg.x + 20, yy, 15, "#7F8FA3", "mono")
        doc.rect(lg.x + 20 + T.measure(f"{u}@", 15, "mono") + 4, yy - 11, rng.uniform(60, 100), 10, "#2C3B50", 3)
        doc.rect(lg.x + 250, yy - 11, rng.uniform(70, 110), 10, "#2C3B50", 3)
    ny = lg.y + 82 + len(users) * 40 + 14
    doc.rect(lg.x + 10, ny - 28, lg.w - 20, 44, p.danger, 6, opacity=0.18)
    doc.rect(lg.x + 10, ny - 28, 4, 44, p.danger)
    doc.text("j.doe@acme.example", lg.x + 24, ny, 16, "#FFFFFF", "mono_bold")
    doc.text("Wint*****26!", lg.r - 20, ny, 16, p.danger, "mono_bold", anchor="end")
    # page -> log: the password leaves with the form
    doc.path(f"M{f(fx + 350)} {f(br.y + 290)}C{f(br.r + 60)} {f(br.y + 290)} {f(lg.x - 80)} {f(ny - 6)} "
             f"{f(lg.x + 4)} {f(ny - 6)}", stroke=p.danger, sw=3.5)
    doc.poly([(lg.x + 6, ny - 6), (lg.x - 10, ny - 14), (lg.x - 10, ny + 2)], p.danger)

    if seized:
        cx, cy = lg.cx, lg.y + 190
        with doc.g(f"rotate(-12 {f(cx)} {f(cy)})", opacity=0.92):
            doc.rect(cx - 150, cy - 44, 300, 88, "none", 8, stroke="#2F6FD8", sw=6)
            doc.rect(cx - 140, cy - 34, 280, 68, "none", 4, stroke="#2F6FD8", sw=2)
            doc.text("SEIZED", cx, cy + 20, 54, "#4F8BEA", "display", anchor="middle", tracking=4)
    doc.focus = Box(60, 50, 1500, 844)
