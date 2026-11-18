"""Session theft through a phishing kit: the victim signs in through the kit,
the kit relays the sign-in to the real service, keeps a copy of the session
token and replays it, so the attacker is in without a password.

Evidence used (s:74611fb5503115): the EvilTokens, Knight Office and Kali365
phishing kits "capture and replay M365 tokens" to "hijack Microsoft 365
logins by stealing sign-in sessions" (Huntress). Nothing else is drawn as
fact: no email address, no code digits, no token string, no domain, no vendor
logo or interface. The sign-in card is a generic silhouette; the service is
named in plain text only when the headline names it.

Two compositions (ALTERNATIVES):

* "a" lanes: the victim's sign-in runs as a thick lane through the kit to the
  service; the kit drops a red copy of the session token, which runs on a
  second lane ("replay") into the same service. Original and copy are the
  same shape: blue in the victim's lane, red in the attacker's.
* "b" one session, two browsers: two large identical signed-in windows, the
  victim's and the attacker's, joined by one token that the kit (a dark
  plate on the seam) has copied from one to the other.

"a" is the default: it shows the whole mechanism (relay, copy, replay) with
three large forms and reads at feed size as "a dark box splits a red token
off the sign-in".
"""
from __future__ import annotations

import random
import re
from typing import Callable

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, icon
from . import scene

_KITS = (("eviltokens", "EvilTokens"), ("knight office", "Knight Office"), ("kali365", "Kali365"))


def _service_name(brief: EditorialBrief) -> str:
    """The service as the sources name it (plain text, no logo)."""
    t = brief.text
    if re.search(r"microsoft 365|\bm365\b|office 365", t):
        return "Microsoft 365"
    if "Google" in brief.entities or re.search(r"\bgoogle\b", t):
        return "Google"
    return ""


def _relay_label(brief: EditorialBrief) -> str:
    """What the sources call the thing in the middle."""
    t = brief.text
    if "phishing kit" in t:
        return "phishing kit"
    if re.search(r"live prox|reverse prox|\bproxy|\bproxies", t):
        return "live proxy"
    return "phishing relay"


def _kits(brief: EditorialBrief) -> list[str]:
    return [name for key, name in _KITS if key in brief.text]


# ---------------------------------------------------------------- objects

def _ticket_d(x: float, y: float, w: float, h: float, notch: float) -> str:
    """A pass / ticket outline: rounded rectangle with a half-round notch in
    each short side."""
    r = 18.0
    cy = y + h / 2
    return (f"M{f(x + r)} {f(y)}H{f(x + w - r)}Q{f(x + w)} {f(y)} {f(x + w)} {f(y + r)}"
            f"V{f(cy - notch)}A{f(notch)} {f(notch)} 0 0 0 {f(x + w)} {f(cy + notch)}"
            f"V{f(y + h - r)}Q{f(x + w)} {f(y + h)} {f(x + w - r)} {f(y + h)}H{f(x + r)}"
            f"Q{f(x)} {f(y + h)} {f(x)} {f(y + h - r)}V{f(cy + notch)}"
            f"A{f(notch)} {f(notch)} 0 0 0 {f(x)} {f(cy - notch)}V{f(y + r)}Q{f(x)} {f(y)} {f(x + r)} {f(y)}Z")


def _token(doc: Doc, cx: float, cy: float, w: float, fill: str, *, angle: float = 0, label: bool = True,
           shadow: bool = True) -> None:
    """The session token as a physical pass: a key glyph and a perforation.
    Deliberately abstract: no token string."""
    h = w * 0.46
    x, y = cx - w / 2, cy - h / 2
    d = _ticket_d(x, y, w, h, h * 0.13)
    with doc.g(transform=f"rotate({f(angle)} {f(cx)} {f(cy)})"):
        if shadow:
            doc.path(d, fill="#0B1A2E", opacity=0.30, extra=f' transform="translate(10 22)" filter="{doc.blur(14)}"')
        doc.path(d, fill=fill)
        doc.path(d, fill=doc.lin([(0, "#FFFFFF", 0.22), (0.5, "#FFFFFF", 0.0), (1, "#000000", 0.10)]))
        stub = x + w * 0.30
        doc.line((stub, y + 14), (stub, y + h - 14), "#FFFFFF", max(2.0, w / 140), 0.55, dash="2 9")
        icon(doc, "key", x + w * 0.15, cy, w * 0.17, "#FFFFFF", max(2.4, w / 90))
        if label:
            size = w * 0.098
            doc.text("session", x + w * 0.37, cy - size * 0.18, size, "#FFFFFF", "ui_bold")
            doc.text("token", x + w * 0.37, cy + size * 0.98, size, "#FFFFFF", "ui_bold")


def _signin(doc: Doc, b: Box, *, accent: str, line: str) -> None:
    """Generic sign-in card silhouette: mark, two fields, a code row, a button.
    No words, no digits: the shapes say 'sign-in' on their own."""
    doc.shadow(b.x, b.y, b.w, b.h, 16, 0.8)
    doc.rect(b.x, b.y, b.w, b.h, "#FFFFFF", 16, stroke=line, sw=1.2)
    px = b.x + b.w * 0.12
    iw = b.w * 0.76
    doc.circle(px + 20, b.y + 52, 20, accent)
    doc.circle(px + 20, b.y + 52, 8, "#FFFFFF")
    doc.rect(px, b.y + 98, iw * 0.52, 16, "#CBD6E2", 8)
    doc.rect(px, b.y + 136, iw, 50, "#F1F5F9", 9, stroke=line, sw=1.4)
    doc.rect(px + 18, b.y + 155, iw * 0.55, 12, "#B9C6D4", 6)
    doc.rect(px, b.y + 202, iw, 50, "#F1F5F9", 9, stroke=accent, sw=2.2)
    for i in range(9):
        doc.circle(px + 24 + i * 20, b.y + 227, 5.5, "#2A3A50")
    n = 6
    gap = 8
    cw = (iw - gap * (n - 1)) / n
    for i in range(n):
        cx = px + i * (cw + gap)
        doc.rect(cx, b.y + 270, cw, 44, "#F1F5F9", 7, stroke=line, sw=1.2)
        doc.circle(cx + cw / 2, b.y + 292, 5, "#2A3A50")
    doc.rect(px, b.y + 334, iw, 50, accent, 9)


def _lane(doc: Doc, x0: float, x1: float, y: float, color: str, h: float = 46, chevrons: bool = True,
          opacity: float = 1.0) -> None:
    doc.rect(x0, y - h / 2, x1 - x0, h, color, h / 2, opacity=opacity)
    if chevrons:
        d = []
        k = h * 0.22
        xx = x0 + 34
        while xx < x1 - 30:
            d.append(f"M{f(xx - k)} {f(y - k * 1.3)}L{f(xx + k * 0.6)} {f(y)}L{f(xx - k)} {f(y + k * 1.3)}")
            xx += 46
        doc.path("".join(d), stroke="#FFFFFF", sw=3.2, opacity=0.55 * opacity)


def _kit_block(doc: Doc, b: Box, label: str, kits: list[str], lane_y: float, lane_col: str) -> None:
    """The phishing kit: a heavy dark block, extruded, with the victim's lane
    running through a channel cut across it (the relay)."""
    dep = 24
    doc.shadow(b.x, b.y, b.w, b.h + dep, 26, 1.3)
    doc.rect(b.x, b.y + dep, b.w, b.h, "#060C16", 26)                   # extrusion
    doc.rect(b.x, b.y, b.w, b.h, doc.lin([(0, "#1F2E44", 1), (1, "#0E1726", 1)]), 26)
    doc.rect(b.x + 1, b.y + 1, b.w - 2, b.h - 2, "none", 25, stroke="#FFFFFF", sw=1.2, opacity=0.12)
    # the channel: the lane visibly passes through the kit
    doc.rect(b.x, lane_y - 38, b.w, 76, "#04080F")
    _lane(doc, b.x - 4, b.r + 4, lane_y, lane_col, chevrons=True)
    doc.rect(b.x, lane_y - 38, b.w, 6, "#000000", opacity=0.45)
    size = min(62.0, (b.w - 48) / max(1.0, T.measure(label, 1, "ui_bold")))
    doc.text(label, b.cx, b.y + 30 + size * 0.69, size, "#FFFFFF", "ui_bold", anchor="middle")
    if kits:
        line = " / ".join(kits)
        ks = min(21.0, (b.w - 50) / max(1.0, T.measure(line, 1, "mono")))
        doc.text(line, b.cx, lane_y - 58, ks, "#9FB2CF", "mono", anchor="middle")


def _service(doc: Doc, b: Box, name: str, ports: tuple[float, float], danger: str, safe: str) -> None:
    """The real service: a tall white panel, named in plain text, with two
    signed-in sessions (the victim's and the replayed one)."""
    p = doc.pal
    doc.shadow(b.x, b.y, b.w, b.h, 22, 1.0)
    doc.rect(b.x, b.y, b.w, b.h, "#FFFFFF", 22, stroke=p.line, sw=1.2)
    if name:
        size = min(40.0, (b.w - 48) / max(1.0, T.measure(name, 1, "ui_bold")))
        doc.text(name, b.cx, b.y + 66, size, p.ink, "ui_bold", anchor="middle")
    doc.line((b.x + 24, b.y + 96), (b.r - 24, b.y + 96), p.line, 1.5)
    for py, col in ((ports[0], p.accent), (ports[1], danger)):
        doc.circle(b.x + 74, py, 36, col, opacity=0.12)
        icon(doc, "user", b.x + 74, py, 46, col, 2.8)
        doc.rect(b.x + 128, py - 18, b.w * 0.38, 13, "#CBD6E2", 6)
        doc.rect(b.x + 128, py + 6, b.w * 0.26, 11, "#E2E8EF", 5)
        icon(doc, "check", b.r - 46, py, 38, safe if col == p.accent else danger, 4)
    # mailbox skeleton between the two sessions: what an open session reaches
    for i in range(3):
        yy = (ports[0] + ports[1]) / 2 - 50 + i * 40
        doc.rect(b.x + 40, yy, b.w - 80, 26, "#F1F5F9", 6)


# ---------------------------------------------------------------- compositions

def _lanes(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.45, 0.1))
    name = _service_name(brief)
    kits = _kits(brief)
    lane_col = "#2B3B52"
    y1, y2 = 330.0, 662.0                     # victim's lane, replay lane
    svc = Box(1262, 110, 290, 700)
    kit = Box(500, 118, 460, 300)

    # victim's sign-in (left) and the lane through the kit to the service
    _lane(doc, 330, svc.x + 20, y1, lane_col)
    _signin(doc, Box(44, 112, 330, 410), accent=p.accent, line=p.line)
    _kit_block(doc, kit, _relay_label(brief), kits, y1, lane_col)
    # inside the channel: the victim's token, and the copy leaving it
    _token(doc, kit.cx, y1, 120, p.accent, label=False, shadow=False)
    doc.path(f"M{f(kit.cx)} {f(y1 + 34)}V{f(y2 - 100)}", stroke=p.danger, sw=6, dash="2 13")
    # the original continues to the service
    _token(doc, 1110, y1, 150, p.accent, label=False, shadow=False)

    # the copy, replayed on its own lane into the same service
    _lane(doc, 990, svc.x + 20, y2, p.danger)
    _service(doc, svc, name, (y1, y2), p.danger, p.safe)
    _token(doc, kit.cx, y2 + 8, 500, p.danger, angle=-6)
    doc.text("replay", 1112, y2 - 58, 84, p.danger, "display", anchor="middle")
    doc.focus = Box(440, 110, 1120, 630)


def _browser(doc: Doc, b: Box, *, dark: bool, accent: str) -> Box:
    """A plain browser frame (no URL text) with a signed-in mailbox skeleton.
    Returns the content box."""
    surf = "#121C2B" if dark else "#FFFFFF"
    chrome = "#0B121E" if dark else "#E6ECF2"
    bar_fill = "#22324A" if dark else "#CBD6E2"
    row = "#1A2638" if dark else "#F1F5F9"
    doc.shadow(b.x, b.y, b.w, b.h, 18, 1.1)
    doc.rect(b.x, b.y, b.w, b.h, surf, 18)
    doc.add(f'<path d="M{f(b.x)} {f(b.y + 18)}Q{f(b.x)} {f(b.y)} {f(b.x + 18)} {f(b.y)}H{f(b.r - 18)}'
            f'Q{f(b.r)} {f(b.y)} {f(b.r)} {f(b.y + 18)}V{f(b.y + 58)}H{f(b.x)}Z" fill="{chrome}"/>')
    for i in range(3):
        doc.circle(b.x + 28 + i * 22, b.y + 29, 7, bar_fill)
    doc.rect(b.x + 110, b.y + 15, b.w - 150, 28, row, 14)
    c = Box(b.x, b.y + 58, b.w, b.h - 58)
    # sidebar + message rows: an open mailbox, as shapes only
    doc.rect(c.x + 24, c.y + 26, c.w * 0.22, c.h - 52, row, 10)
    for i in range(5):
        yy = c.y + 30 + i * (c.h - 60) / 5
        doc.circle(c.x + c.w * 0.31, yy + 22, 15, bar_fill)
        doc.rect(c.x + c.w * 0.36, yy + 8, c.w * (0.36 if i % 2 else 0.46), 12, bar_fill, 6)
        doc.rect(c.x + c.w * 0.36, yy + 30, c.w * 0.52, 9, row, 4)
    icon(doc, "user", c.x + 24 + c.w * 0.11, c.y + 70, 44, accent, 2.8)
    return c


def _twins(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.25, 0.2))
    # the attacker's half of the frame is dark: a hard diagonal split
    doc.poly([(960, 0), (1600, 0), (1600, 900), (700, 900)], "#0D1626")
    doc.poly([(960, 0), (974, 0), (714, 900), (700, 900)], p.danger, opacity=0.9)
    name = _service_name(brief)
    kits = _kits(brief)
    _browser(doc, Box(56, 120, 660, 500), dark=False, accent=p.accent)
    _browser(doc, Box(990, 150, 570, 470), dark=True, accent=p.danger)
    if name:
        doc.text(name, 64, 88, 40, p.ink, "ui_bold")
    doc.text("replay", 1275, 112, 84, p.danger, "display", anchor="middle")
    # the chain along the bottom: the victim's token -> the kit -> its copy
    ty = 742.0
    doc.path(f"M380 {f(ty)}H1150", stroke=p.danger, sw=6, dash="2 13")
    _token(doc, 330, ty, 330, p.accent)
    plate = Box(600, ty - 82, 400, 164)
    doc.shadow(plate.x, plate.y, plate.w, plate.h, 22, 1.1)
    doc.rect(plate.x, plate.y, plate.w, plate.h, "#05090F", 22)
    doc.rect(plate.x + 1, plate.y + 1, plate.w - 2, plate.h - 2, "none", 21, stroke="#FFFFFF", sw=1.2,
             opacity=0.14)
    label = _relay_label(brief)
    size = min(56.0, (plate.w - 48) / max(1.0, T.measure(label, 1, "ui_bold")))
    doc.text(label, plate.cx, plate.y + 30 + size * 0.69, size, "#FFFFFF", "ui_bold", anchor="middle")
    if kits:
        line = " / ".join(kits)
        ks = min(20.0, (plate.w - 40) / max(1.0, T.measure(line, 1, "mono")))
        doc.text(line, plate.cx, plate.b - 30, ks, "#9FB2CF", "mono", anchor="middle")
    _token(doc, 1270, ty + 6, 440, p.danger, angle=-5)
    doc.focus = Box(160, 80, 1320, 742)


ALTERNATIVES: dict[str, Callable[[Doc, EditorialBrief, random.Random], None]] = {"a": _lanes, "b": _twins}


@scene("session_theft")
def session_theft(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    _lanes(doc, brief, rng)
