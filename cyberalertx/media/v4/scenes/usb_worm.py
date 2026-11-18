"""USB worms: an infected flash drive in a laptop, and the worm's copies
moving to other drives and machines. Two compositions:

* `fanout` (the sources describe the second-stage chain): the infected laptop
  is the hero, its screen showing the chain the sources name, with copies
  fanning out to other drives and computers.
* `chain` (otherwise): one hop after another along a row of drives and
  computers, the way removable-media spread actually travels.

Generic hardware, no vendor marks. Names on screen come only from the sources."""
from __future__ import annotations

import random
import re

from ..brief import EditorialBrief
from ..kit import Box, Doc, f, icon, pill
from . import scene

_DRIVE_COLORS = (("#2D3A34", "#46584F"), ("#2B3442", "#46536A"), ("#3A2F2A", "#5A4A40"), ("#30303A", "#4A4A58"))


def _usb(doc: Doc, x: float, y: float, s: float, rot: float, body: tuple[str, str], infected: bool,
         danger: str, opacity: float = 1.0) -> tuple[float, float]:
    """A flash drive, 3/4 top view, connector pointing right. (x, y) = centre.
    Returns the tip of the connector."""
    w, h = 150 * s, 52 * s
    with doc.g(f"translate({f(x)} {f(y)}) rotate({f(rot)})", opacity=opacity):
        doc.rect(-w / 2 + 6 * s, -h / 2 + 12 * s, w, h, "#000", 10 * s, opacity=0.45,
                 extra=f' filter="{doc.blur(round(8 * s) or 1)}"')
        # metal connector
        cx0 = w / 2 - 4 * s
        doc.rect(cx0, -h * 0.34, 46 * s, h * 0.68, doc.lin([(0, "#E9EDF1", 1), (0.5, "#9BA4AE", 1),
                                                           (1, "#C9D0D7", 1)]), 3 * s)
        for k in (0, 1):
            doc.rect(cx0 + 12 * s + k * 16 * s, -h * 0.12, 8 * s, 8 * s, "#59616B", 1)
        # body (with a side face for thickness)
        doc.rect(-w / 2, -h / 2 + 6 * s, w, h, body[0], 10 * s)
        doc.rect(-w / 2, -h / 2, w, h, doc.lin([(0, body[1], 1), (1, body[0], 1)]), 10 * s)
        doc.rect(-w / 2 + 6 * s, -h / 2 + 3 * s, w - 12 * s, 4 * s, "#FFFFFF", 2 * s, opacity=0.14)
        # key-ring hole and grip lines
        doc.circle(-w / 2 + 16 * s, 0, 6 * s, "#0B0F0D")
        for k in range(4):
            doc.rect(-w / 2 + 40 * s + k * 12 * s, -h / 2 + 12 * s, 3 * s, h - 24 * s, "#000", 1, opacity=0.18)
        # activity LED
        led = danger if infected else "#7CE0A8"
        doc.circle(w / 2 - 20 * s, 0, 5 * s, led)
        if infected:
            doc.circle(w / 2 - 20 * s, 0, 14 * s, led, opacity=0.25)
    import math
    a = math.radians(rot)
    tip = w / 2 + 42 * s
    return x + tip * math.cos(a), y + tip * math.sin(a)


def _laptop(doc: Doc, x: float, y: float, w: float) -> tuple[Box, tuple[float, float]]:
    """Open laptop, front view with the deck in slight perspective. Returns
    (screen box, left-side port point)."""
    sh = w * 0.62
    deck = w * 0.13
    doc.add(f'<ellipse cx="{f(x + w / 2)}" cy="{f(y + sh + deck + 10)}" rx="{f(w * 0.62)}" ry="{f(w * 0.05)}" '
            f'fill="#000" opacity="0.55" filter="{doc.blur(14)}"/>')
    # lid
    doc.rect(x, y, w, sh, doc.lin([(0, "#2E3A34", 1), (1, "#1A2420", 1)]), 16)
    doc.rect(x + 2, y + 2, w - 4, 3, "#FFFFFF", 2, opacity=0.12)
    scr = Box(x + 20, y + 20, w - 40, sh - 34)
    # deck: a trapezoid seen from above
    m = w * 0.06
    doc.path(f"M{f(x - m * 0.2)} {f(y + sh)}H{f(x + w + m * 0.2)}L{f(x + w + m)} {f(y + sh + deck)}"
             f"H{f(x - m)}Z", fill=doc.lin([(0, "#3F4D46", 1), (1, "#25302B", 1)]))
    # keyboard rows (texture), trackpad
    for r in range(3):
        yy = y + sh + 10 + r * (deck - 30) / 3
        inset = m * (0.2 + 0.8 * (r + 0.5) / 3)
        doc.rect(x - inset + 40, yy, w + 2 * inset - 80, (deck - 34) / 3 - 4, "#1C2622", 3)
    doc.rect(x + w / 2 - w * 0.12, y + sh + deck - 22, w * 0.24, 14, "#33413A", 4)
    doc.rect(x - m, y + sh + deck - 4, w + 2 * m, 8, "#1A2420", 4)
    return scr, (x - m * 0.6, y + sh + deck * 0.55)


def _pc(doc: Doc, x: float, y: float, w: float) -> Box:
    """Small desktop monitor on a stand. Returns the screen box."""
    h = w * 0.62
    doc.add(f'<ellipse cx="{f(x + w / 2)}" cy="{f(y + h + w * 0.2)}" rx="{f(w * 0.34)}" ry="{f(w * 0.04)}" '
            f'fill="#000" opacity="0.5" filter="{doc.blur(8)}"/>')
    doc.path(f"M{f(x + w * 0.44)} {f(y + h)}L{f(x + w * 0.41)} {f(y + h + w * 0.17)}H{f(x + w * 0.59)}"
             f"L{f(x + w * 0.56)} {f(y + h)}Z", fill="#25302B")
    doc.rect(x + w * 0.3, y + h + w * 0.16, w * 0.4, w * 0.04, "#33413A", 4)
    doc.rect(x, y, w, h, doc.lin([(0, "#2E3A34", 1), (1, "#1A2420", 1)]), 10)
    return Box(x + 10, y + 10, w - 20, h - 22)


def _screen_files(doc: Doc, s: Box, rng: random.Random, danger: str, ink: str, label: str = "USB DRIVE") -> None:
    """A removable drive's contents: ordinary files and the worm's copy."""
    doc.rect(s.x, s.y, s.w, s.h, "#E9F0EC", 4)
    doc.rect(s.x, s.y, s.w, 26, "#CFDCD4", 4)
    doc.text(label, s.x + 12, s.y + 18, 13, "#1B2A22", "ui_bold", tracking=1)
    cols = 3
    cw = (s.w - 24) / cols
    for k in range(6):
        cx, cy = s.x + 12 + (k % cols) * cw + cw / 2, s.y + 54 + (k // cols) * 66
        bad = k == 4
        col = danger if bad else "#6B8577"
        doc.path(f"M{f(cx - 13)} {f(cy - 16)}h17l9 9v25h-26z", fill="#FFFFFF", stroke=col, sw=2)
        doc.rect(cx - cw / 2 + 10, cy + 22, cw - 20, 7, col, 3, opacity=0.9 if bad else 0.45)
        if bad:
            doc.circle(cx + 13, cy - 16, 8, danger)


def _copy_chip(doc: Doc, x: float, y: float, danger: str) -> None:
    doc.rect(x - 16, y - 20, 32, 40, "#FFFFFF", 4, stroke=danger, sw=2)
    doc.path(f"M{f(x - 9)} {f(y - 8)}h18M{f(x - 9)} {f(y)}h18M{f(x - 9)} {f(y + 8)}h11", stroke=danger, sw=2)


def _hop(doc: Doc, a: tuple[float, float], b: tuple[float, float], color: str, bend: float = 0.0) -> None:
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + bend
    doc.path(f"M{f(a[0])} {f(a[1])}Q{f(mx)} {f(my)} {f(b[0])} {f(b[1])}", stroke=color, sw=3, dash="3 9")
    _copy_chip(doc, (a[0] + 2 * mx + b[0]) / 4, (a[1] + 2 * my + b[1]) / 4, color)


@scene("usb_worm")
def usb_worm(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    doc.rect(0, 0, 1600, 900, doc.lin([(0, "#13201A", 1), (1, "#070C0A", 1)], 0, 0, 0.3, 1))
    doc.rect(0, 0, 1600, 900, doc.rad([(0, "#7CE0A8", 0.10), (1, "#7CE0A8", 0)], 0.35, 0.3, 0.6))
    names = [n for n in ("Retadup", "CoffeeLoader") if n.lower() in text]
    chain = re.search(r"7z\.dll|rundll32", text) is not None
    # a desk surface
    desk = 640 if chain else 690
    doc.rect(0, desk, 1600, 900 - desk, doc.lin([(0, "#1A2620", 1), (1, "#0C120F", 1)]))
    doc.line((0, desk), (1600, desk), "#2C3D34", 2)

    if chain:
        # ---------------- fan-out: infected laptop is the hero
        # the infected drive goes in first so the laptop's side hides its connector
        _usb(doc, 300 - 640 * 0.06 * 0.6 - 92, 200 + 640 * 0.62 + 640 * 0.13 * 0.5, 1.0, 0, _DRIVE_COLORS[0], True,
             p.danger)
        scr, port = _laptop(doc, 300, 200, 640)
        # terminal on the laptop: the chain the sources describe
        doc.rect(scr.x, scr.y, scr.w, scr.h, "#08100C", 4)
        doc.text("removable drive  ->  worm  ->  loader", scr.x + 24, scr.y + 40, 18, "#7F988A", "mono")
        rows = [("> installer.exe", "#E6F0EA"), ("  drops %TEMP%\\7z.dll", "#E6F0EA"),
                ("> rundll32.exe 7z.dll", p.danger)]
        if "CoffeeLoader" in names:
            rows.append(("  CoffeeLoader running", p.danger))
        for k, (t, c) in enumerate(rows):
            doc.text(t, scr.x + 24, scr.y + 96 + k * 44, 24, c, "mono_bold" if c == p.danger else "mono")
        doc.rect(scr.x + 24, scr.y + 96 + len(rows) * 44 - 18, 14, 24, "#7CE0A8", opacity=0.8)
        # copies leaving to other drives and machines
        src = (940, 470)
        targets = [("usb", 1180, 270, -8), ("pc", 1330, 440, 0), ("usb", 1190, 760, 10)]
        for kind, tx, ty, rot in targets:
            if kind == "usb":
                _usb(doc, tx, ty, 0.8, rot, _DRIVE_COLORS[1 + (tx // 10) % 3], True, p.danger)
                _hop(doc, src, (tx - 70, ty), p.danger, -40 if ty < src[1] else 40)
            else:
                s = _pc(doc, tx, ty - 110, 220)
                _screen_files(doc, s, rng, p.danger, p.ink, "E:\\")
                _hop(doc, src, (tx - 10, ty - 40), p.danger, 0)
        years = brief.facts.get("years")
        title = names[0] if names else "USB worm"
        doc.text(title, 300, 140, 46, p.ink, "display")
        if years and re.search(r"after (the )?takedown|takedown", text):
            pill(doc, 300 + doc_width(title, 46) + 24, 104, f"back {years} years after takedown", fg="#0B1310",
                 bg="#F2C14E", size=16, font="ui_bold")
        doc.focus = Box(160, 100, 1280, 720)
    else:
        # ---------------- chain: drive -> PC -> drive -> laptop -> ...
        doc.add('<g transform="translate(0 50)">')
        _usb(doc, 170, 560, 1.15, -6, _DRIVE_COLORS[0], True, p.danger)
        s1 = _pc(doc, 330, 300, 360)
        _screen_files(doc, s1, rng, p.danger, p.ink, "USB DRIVE (E:)")
        lx, ly, lw = 1060, 330, 400
        _usb(doc, lx - lw * 0.036 - 66, ly + lw * 0.62 + lw * 0.13 * 0.5, 0.9, 0, _DRIVE_COLORS[1], True, p.danger)
        scr, port = _laptop(doc, lx, ly, lw)
        _screen_files(doc, scr, rng, p.danger, p.ink, "USB DRIVE (F:)")
        _hop(doc, (250, 520), (360, 430), p.danger, -50)
        _hop(doc, (700, 470), (930, 560), p.danger, -90)
        # faded next hop, toward the next drive
        _usb(doc, 1340, 720, 0.75, -6, _DRIVE_COLORS[2], True, p.danger, opacity=0.5)
        doc.path("M1480 640Q1500 700 1440 712", stroke=p.danger, sw=3, dash="3 9", opacity=0.5)
        title = names[0] if names else "USB worm"
        doc.text(title, 330, 200, 50, p.ink, "display")
        sub = "copies itself to every drive it meets"
        doc.text(sub, 332, 240, 21, p.muted, "ui")
        if "CoffeeLoader" in names:
            pill(doc, 1060, 270, "delivers CoffeeLoader", fg="#FFFFFF", bg=p.danger, size=16, font="ui_bold")
        doc.add("</g>")
        doc.focus = Box(110, 120, 1380, 776)
    _ = icon


def doc_width(s: str, size: float) -> float:
    from .. import type as T
    return T.measure(T.supported(s, "display"), size, "display")
