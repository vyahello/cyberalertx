"""Breach notifications: the letter the affected people receive, and the
personal records it is about. The record cards change with the people the
sources name (drivers, employees, customers, payment cards); when the sources
say the data sat with a third-party or cloud provider, the cards come out of
that provider's storage. The affected count appears only when the sources
state it, with their own qualifier (nearly / more than)."""
from __future__ import annotations

import random
import re

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, f, icon
from . import scene

_PAPER = "#FFFDF8"


def count_label(brief: EditorialBrief) -> tuple[str, str]:
    """(figure, noun) for the affected count, or ("", "")."""
    fx = brief.facts
    for key, noun in (("people", "people"), ("records", "records"), ("accounts", "accounts")):
        v = fx.get(key)
        if not v:
            continue
        v = str(v)
        if "." in v:                                   # "37.6" only makes sense with its unit
            m = re.search(re.escape(v) + r"\d*\s*(m\b|million|млн)", brief.text or "")
            if not m:
                continue
            v += "M"
        if fx.get(key + "_approx"):
            v = "~" + v
        elif fx.get(key + "_plus"):
            v += "+"
        return v, noun
    return "", ""


def _kind(text: str) -> str:
    if re.search(r"payment card|credit card|card details|платіжн\w* карт", text):
        return "payment"
    if re.search(r"\bdrivers?\b|водії", text):
        return "driver"
    if re.search(r"employee|staff|співробітник|працівник", text):
        return "employee"
    if re.search(r"email address|newsletter|subscriber", text):
        return "email"
    return "customer"


# ---------------------------------------------------------------- record cards (drawn at 0,0)

def _redact(doc: Doc, x: float, y: float, w: float, h: float = 14) -> None:
    doc.rect(x, y, w, h, "#24252B", 2)


def _portrait(doc: Doc, x: float, y: float, w: float, h: float, bg: str) -> None:
    doc.rect(x, y, w, h, bg, 4)
    with doc.g(clip=doc.clip_rect(x, y, w, h, 4)):
        doc.circle(x + w / 2, y + h * 0.4, w * 0.22, "#9AA0AD")
        doc.add(f'<ellipse cx="{f(x + w / 2)}" cy="{f(y + h * 1.02)}" rx="{f(w * 0.45)}" ry="{f(h * 0.38)}" '
                f'fill="#9AA0AD"/>')


def _wheel(doc: Doc, cx: float, cy: float, r: float, color: str) -> None:
    doc.circle(cx, cy, r, "none", color, r * 0.16)
    doc.circle(cx, cy, r * 0.22, color)
    for a in ((-r * 0.9, r * 0.1), (r * 0.9, r * 0.1), (0, r * 0.92)):
        doc.line((cx, cy), (cx + a[0], cy + a[1]), color, r * 0.16)


def _record_card(doc: Doc, kind: str, w: float, h: float, rng: random.Random, front: bool,
                 accent: str, danger: str) -> None:
    doc.rect(0, 0, w, h, _PAPER, 10, stroke="#CFC6B5", sw=1.2)
    if kind == "driver":
        doc.rect(0, 0, w, 44, "#1F2430", 10)
        doc.rect(0, 30, w, 14, "#1F2430")
        _wheel(doc, 26, 22, 12, "#FFFFFF")
        doc.text("DRIVER PROFILE", 48, 29, 16, "#FFFFFF", "ui_bold", tracking=1.5)
        _portrait(doc, 20, 62, 92, 112, "#E3DED3")
        labels = ("name", "licence", "phone", "vehicle")
    else:
        doc.rect(0, 0, w, 44, "#EFE9DE", 10)
        doc.rect(0, 30, w, 14, "#EFE9DE")
        icon(doc, "user", 26, 22, 22, "#17181C", 2)
        doc.text("CUSTOMER RECORD" if kind == "customer" else "SUBSCRIBER", 48, 29, 16, "#17181C", "ui_bold",
                 tracking=1.5)
        _portrait(doc, 20, 62, 92, 112, "#E8E2D6")
        labels = ("name", "email", "phone", "address") if kind == "customer" else ("email", "list", "since", "id")
    for i, lab in enumerate(labels):
        y = 72 + i * 30
        doc.text(lab, 130, y + 11, 13, "#7A7466", "ui")
        _redact(doc, 196, y, rng.uniform(70, w - 230))
    if front:
        doc.rect(0, 0, w, h, "none", 10, stroke=danger, sw=3)


def _badge(doc: Doc, w: float, h: float, rng: random.Random, front: bool, accent: str, danger: str) -> None:
    """Employee ID badge, portrait orientation, on a lanyard clip."""
    doc.rect(0, 0, w, h, _PAPER, 12, stroke="#CFC6B5", sw=1.2)
    doc.rect(w / 2 - 26, 16, 52, 10, "#D8D1C2", 5)                # slot
    doc.rect(0, 44, w, 40, accent, 0)
    doc.text("EMPLOYEE", w / 2, 71, 18, "#FFFFFF", "ui_bold", anchor="middle", tracking=3)
    _portrait(doc, w / 2 - 56, 104, 112, 132, "#E3DED3")
    _redact(doc, 24, 256, w - 48, 16)
    _redact(doc, 46, 284, w - 92, 11)
    for i in range(22):                                           # barcode
        bw = rng.choice((2, 3, 5))
        doc.rect(26 + i * ((w - 52) / 22), h - 50, bw, 30, "#24252B")
    if front:
        doc.rect(0, 0, w, h, "none", 12, stroke=danger, sw=3)
    # clip and strap
    doc.rect(w / 2 - 14, -34, 28, 40, doc.lin([(0, "#9AA1AB", 1), (0.5, "#F2F4F6", 1), (1, "#8A919B", 1)], 0, 0, 1, 0),
             5)


def _payment(doc: Doc, w: float, h: float, rng: random.Random, front: bool, danger: str) -> None:
    base = rng.choice(("#2B3448", "#3A2E4F", "#24453F", "#4A3426"))
    doc.rect(0, 0, w, h, doc.lin([(0, base, 1), (1, "#111317", 1)], 0, 0, 1, 1), 14)
    doc.rect(28, 64, 50, 38, doc.lin([(0, "#E9D49A", 1), (1, "#A88A45", 1)], 0, 0, 1, 1), 6)
    doc.path("M28 83H78M45 64V102M61 64V102", stroke="#8A7038", sw=1.2)
    digits = "".join(rng.choice("0123456789") for _ in range(4))
    doc.text(f"**** **** **** {digits}", 28, 150, 22, "#FFFFFF", "mono", opacity=0.92)
    doc.text("MM/YY", 28, 184, 13, "#FFFFFF", "mono", opacity=0.7)
    doc.circle(w - 64, h - 40, 16, "#FFFFFF", opacity=0.25)
    doc.circle(w - 44, h - 40, 16, "#FFFFFF", opacity=0.18)
    if front:
        doc.rect(-4, -4, w + 8, h + 8, "none", 16, stroke=danger, sw=3)


# ---------------------------------------------------------------- the letter

def _letter(doc: Doc, x: float, y: float, w: float, h: float, sender: str, kind: str, provider: str,
            rng: random.Random) -> None:
    p = doc.pal
    # envelope behind the letter
    ex, ey = x - 60, y + h - 330
    doc.shadow(ex, ey, w + 40, 300, 6, 0.8)
    doc.rect(ex, ey, w + 40, 300, "#E9E0CD", 6, stroke="#CDBFA5", sw=1)
    doc.path(f"M{f(ex)} {f(ey)}L{f(ex + (w + 40) / 2)} {f(ey + 150)}L{f(ex + w + 40)} {f(ey)}", stroke="#CDBFA5",
             sw=1.5)
    # the letter
    doc.shadow(x, y, w, h, 3, 1.0)
    doc.rect(x, y, w, h, _PAPER, 3)
    # three-fold creases
    for k in (1, 2):
        cy = y + h * k / 3
        doc.rect(x, cy - 1, w, 2, "#000", opacity=0.05)
        doc.rect(x, cy + 1, w, 6, doc.lin([(0, "#000", 0.05), (1, "#000", 0)]))
    pad = 56
    if sender:
        doc.text(sender, x + pad, y + 70, 22, p.ink, "ui_bold")
    doc.text("Notice of Data Breach", x + pad, y + 140, 46, p.ink, "display")
    salutation = {"driver": "Dear driver,", "employee": "Dear colleague,", "payment": "Dear customer,",
                  "email": "Dear subscriber,"}.get(kind, "Dear customer,")
    doc.text(salutation, x + pad, y + 192, 20, p.ink, "ui")
    heads = ("What happened", "What information was involved", "What we are doing", "What you can do")
    yy = y + 236
    for i, hd in enumerate(heads):
        doc.text(hd, x + pad, yy, 19, p.ink, "ui_bold")
        n = 3 if i < 2 else 2
        for k in range(n):
            lw = (w - 2 * pad) * (rng.uniform(0.55, 0.8) if k == n - 1 else rng.uniform(0.9, 1.0))
            doc.rect(x + pad, yy + 16 + k * 22, lw, 9, "#D9D2C4", 3)
        if i == 0 and provider:
            # the one legible clause: where it happened
            ly = yy + 16 + n * 22
            doc.rect(x + pad - 8, ly - 4, w - 2 * pad + 16, 34, p.danger, 4, opacity=0.1)
            doc.rect(x + pad - 8, ly - 4, 4, 34, p.danger)
            doc.text(f"...at a third-party {provider} provider".replace("  ", " "), x + pad + 6, ly + 19, 18,
                     p.danger, "mono_bold")
            yy += 40
        yy += 16 + n * 22 + 34
    # closing and signature
    doc.text("Sincerely,", x + pad, y + h - 120, 19, p.ink, "ui")
    doc.path(f"M{f(x + pad)} {f(y + h - 66)}c18-30 30-34 26-8s-10 26 6 6 22-24 30-6 14 10 34-6 18-6 40-2",
             stroke="#2B3550", sw=2.4)
    doc.rect(x + pad, y + h - 48, 180, 8, "#D9D2C4", 3)


def _tray_back(doc: Doc, x: float, y: float, w: float) -> None:
    """Interior of the provider's open storage drawer (drawn before the cards)."""
    doc.path(f"M{f(x + 20)} {f(y)}L{f(x + 50)} {f(y - 44)}H{f(x + w - 50)}L{f(x + w - 20)} {f(y)}Z",
             fill=doc.lin([(0, "#0E1116", 1), (1, "#262B35", 1)]))


def _tray_front(doc: Doc, x: float, y: float, w: float, h: float, label: str) -> None:
    """Front panel of the drawer, covering the bottom of the cards."""
    p = doc.pal
    doc.shadow(x, y, w, h, 12, 0.9)
    doc.rect(x, y, w, h, doc.lin([(0, "#343A47", 1), (1, "#1A1E26", 1)]), 12)
    doc.rect(x + 8, y + 4, w - 16, 3, "#FFFFFF", 2, opacity=0.18)
    cx, cy = x + 56, y + h / 2 + 2
    doc.path(f"M{f(cx - 24)} {f(cy + 13)}H{f(cx + 24)}A13 13 0 0 0 {f(cx + 22)} {f(cy - 11)}A17 17 0 0 0 "
             f"{f(cx - 11)} {f(cy - 15)}A13 13 0 0 0 {f(cx - 24)} {f(cy + 13)}Z", stroke="#FFFFFF", sw=2.6)
    doc.text(label, x + 100, cy - 2, 21, "#FFFFFF", "ui_bold")
    doc.text("storage  /records", x + 100, cy + 24, 15, "#A9B0BE", "mono")
    for k in range(3):
        doc.circle(x + w - 34, y + 30 + k * 18, 4, p.danger if k == 0 else "#4ADE80")


# ---------------------------------------------------------------- scene

@scene("breach_notice")
def breach_notice(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    doc.rect(0, 0, 1600, 900, doc.lin([(0, "#EEE8DC", 1), (1, "#DCD2BF", 1)], 0, 0, 0.3, 1))
    doc.rect(0, 0, 1600, 900, doc.rad([(0, "#FFFFFF", 0.6), (1, "#FFFFFF", 0)], 0.25, 0.15, 0.7))

    kind = _kind(text)
    provider = re.search(r"cloud provider|infrastructure provider|third-party (cloud|provider|vendor)|outside vendor|"
                         r"хмарн", text) is not None
    where = "cloud" if re.search(r"cloud|хмар", text) else "AI" if re.search(r"\bai infrastructure", text) else ""
    # the sender: the organisation the sources say is notifying / confirming
    sender = next((e for e in brief.entities if len(e) <= 24 and re.search(
        r"\b" + re.escape(e.lower()) + r"\b,? (says|said|notif|is notifying|confirm|disclos|warn|announc|found|"
        r"employee|customer|newsletter)", text)), "")
    figure, noun = count_label(brief)
    if noun == "people" and kind == "driver":
        noun = "drivers notified"
    elif noun == "people" and kind == "employee":
        noun = "employees affected"
    elif noun == "people":
        noun = "people affected"

    # ---- the letter (hero), turned slightly on the desk
    lx, ly, lw, lh = 130, 70, 640, 800
    with doc.g(f"rotate(-2.5 {f(lx + lw / 2)} {f(ly + lh / 2)})"):
        _letter(doc, lx, ly, lw, lh, sender, kind, (where or " ") if provider else "", rng)

    # ---- the records: a fan of cards (out of the provider's drawer when there is one)
    if kind == "employee":
        cw, ch = 250, 360
    elif kind == "payment":
        cw, ch = 360, 226
    else:
        cw, ch = 420, 200
    n = 5
    ox, oy = 1160.0, 420.0 if kind != "employee" else 450.0
    tray_y = 690
    if provider:
        oy = tray_y - ch / 2 + (40 if kind == "employee" else 10)
        _tray_back(doc, 870, tray_y - 10, 620)
    for i in range(n):
        front = i == n - 1
        rot = -16 + i * 7 + rng.uniform(-1.5, 1.5)
        dx = -150 + i * 62
        dy = 24 - i * 14 + (abs(i - 2) * 8)
        if provider:
            rot = -12 + i * 6 + rng.uniform(-1, 1)
            dy = -abs(i - 2) * 10 - i * 12
            dx = -100 + i * 48
        tx, ty = ox + dx - cw / 2, oy + dy - ch / 2
        doc.add(f'<g transform="translate({f(tx)} {f(ty)}) rotate({f(rot)} {f(cw / 2)} {f(ch / 2)})">')
        doc.rect(4, 14, cw, ch, "#000", 10, opacity=0.16, extra=f' filter="{doc.blur(9)}"')
        if kind == "employee":
            _badge(doc, cw, ch, rng, front, p.accent, p.danger)
        elif kind == "payment":
            _payment(doc, cw, ch, rng, front, p.danger)
        else:
            _record_card(doc, kind, cw, ch, rng, front, p.accent, p.danger)
        doc.add("</g>")
    if provider:
        _tray_front(doc, 850, tray_y, 660, 120, f"third-party {where} provider".replace("  ", " "))

    # ---- the count (only when the sources state it), else what the records are
    fallback = {"payment": "payment card details", "employee": "employee data", "driver": "driver data",
                "email": "email addresses"}.get(kind, "customer records")
    if figure:
        size = 92 if provider else 104
        y0 = 150 if provider else 790
        w = doc.text(figure, 870, y0, size, p.ink, "display")
        doc.text(noun, 870 + w + 18, y0 - 4, 26, p.danger, "ui_bold")
    else:
        doc.text(fallback, 870, 150 if provider else 790, 52, p.ink, "display")
    _ = T
    doc.focus = Box(140, 70, 1400, 788)
